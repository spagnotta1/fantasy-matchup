<#
.SYNOPSIS
    Replace the local Postgres warehouse with a copy of Railway production.

.DESCRIPTION
    Read-only against Railway: the only thing that touches production is
    pg_dump. The local restore runs in a single transaction - drop the public
    schema, recreate it, load the dump - so a failed pull rolls back and leaves
    the local database exactly as it was. Anything local-only in `public` is
    replaced, not merged.

    Uses the pg_dump/pg_restore/psql from the local PostgreSQL install. When
    Railway runs a newer major version than those tools, the dump runs in a
    throwaway postgres:<major> container instead (Docker Desktop is started if
    needed); the restore always uses local psql.

    Needs the Railway Postgres service to have public networking (TCP proxy)
    enabled, which is what populates DATABASE_PUBLIC_URL. The private
    DATABASE_URL resolves to postgres.railway.internal and is unreachable from
    this machine.

.EXAMPLE
    .\scripts\pull_railway_db.ps1                 # pull now
    .\scripts\pull_railway_db.ps1 -Register       # also pull daily at 07:30
    .\scripts\pull_railway_db.ps1 -Unregister     # stop the daily pull
#>
[CmdletBinding()]
param(
    [string]$RailwayService = "Postgres",
    [string]$RailwayEnvironment = "production",
    [string]$LocalUrl = "postgresql://nflfp:nflfp@localhost:5432/nflfp",
    [int]$KeepDumps = 3,
    [switch]$Register,
    [string]$At = "07:30",
    [switch]$Unregister
)

# Not "Stop": in PowerShell 5.1 that turns any native stderr (psql NOTICEs,
# pg_dump warnings) into a terminating error. Exit codes are checked
# explicitly instead.
$ErrorActionPreference = "Continue"
$TaskName = "nflfp - pull Railway database"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DumpDir = Join-Path $RepoRoot "data\railway"
$LogFile = Join-Path $DumpDir "pull.log"

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

# Native commands don't throw on a non-zero exit in PowerShell 5.1.
function Invoke-Native([string]$what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

if ($Register) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" `
        -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    # StartWhenAvailable: a pull missed while the machine was asleep runs on wake.
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Force | Out-Null
    Write-Host "Registered '$TaskName' daily at $At. Log: $LogFile"
    return
}

New-Item -ItemType Directory -Force -Path $DumpDir -ErrorAction Stop | Out-Null

try {
    # The one guard that matters: this script destroys the target's public
    # schema, so the target must be this machine.
    $localHost = ([uri]($LocalUrl -replace '^postgres(ql)?://', 'http://')).Host
    if ($localHost -notin @("localhost", "127.0.0.1", "::1")) {
        throw "Refusing to overwrite non-local database host '$localHost'"
    }

    # --- Local tools: newest installed PostgreSQL ------------------------------
    $bin = Get-ChildItem "$env:ProgramFiles\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [int]$_.Directory.Parent.Name } -Descending | Select-Object -First 1
    if (-not $bin) { throw "No PostgreSQL install found under $env:ProgramFiles\PostgreSQL" }
    $bin = $bin.DirectoryName
    $toolsMajor = [int](Split-Path (Split-Path $bin -Parent) -Leaf)

    # --- Source: Railway's public URL -----------------------------------------
    $json = railway variables --service $RailwayService --environment $RailwayEnvironment --json
    if ($LASTEXITCODE -ne 0) { throw "railway variables failed - run 'railway login' and 'railway link'" }
    $source = ($json | Out-String | ConvertFrom-Json).DATABASE_PUBLIC_URL
    if (-not $source) {
        throw ("Railway service '$RailwayService' has no DATABASE_PUBLIC_URL. Enable it under " +
               "Postgres -> Settings -> Networking -> Public Networking (TCP proxy).")
    }
    $source = $source -replace '^postgres://', 'postgresql://'
    if ($source -notmatch 'sslmode=') {
        if ($source -match '\?') { $source += "&sslmode=require" } else { $source += "?sslmode=require" }
    }

    $versionNum = & "$bin\psql.exe" $source -tAc "show server_version_num"
    if ($LASTEXITCODE -ne 0) { throw "Could not connect to Railway Postgres" }
    $railwayMajor = [math]::Floor([int]"$versionNum".Trim() / 10000)
    # pg_dump refuses a server newer than itself. When Railway is ahead of the
    # local install, dump and render to SQL from a matching postgres image; the
    # restore still runs with local psql.
    $useDocker = $railwayMajor -gt $toolsMajor
    if ($useDocker) {
        docker info *> $null
        if ($LASTEXITCODE -ne 0) {
            Log "Railway is Postgres $railwayMajor, local tools $toolsMajor; starting Docker Desktop for pg_dump"
            Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
            $deadline = (Get-Date).AddMinutes(3)
            do {
                Start-Sleep -Seconds 5
                docker info *> $null
            } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
            if ($LASTEXITCODE -ne 0) { throw "Docker did not come up within 3 minutes" }
        }
    }
    $image = "postgres:$railwayMajor"

    # --- Dump -----------------------------------------------------------------
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $dumpName = "nflfp-$stamp.dump"
    $dump = Join-Path $DumpDir $dumpName
    $how = "local tools"
    if ($useDocker) { $how = $image }
    Log "Dumping Railway ($RailwayEnvironment, Postgres $railwayMajor) via $how -> $dump"
    Invoke-Native "pg_dump" {
        if ($useDocker) {
            docker run --rm -v "${DumpDir}:/dump" $image `
                pg_dump --format=custom --no-owner --no-acl --file="/dump/$dumpName" $source
        } else {
            & "$bin\pg_dump.exe" --format=custom --no-owner --no-acl --file=$dump $source
        }
    }

    # --- Restore: one transaction, all or nothing ------------------------------
    $sql = Join-Path $DumpDir "restore.sql"
    Invoke-Native "pg_restore (to SQL)" {
        if ($useDocker) {
            docker run --rm -v "${DumpDir}:/dump" $image `
                pg_restore --no-owner --no-acl --file=/dump/restore.sql "/dump/$dumpName"
        } else {
            & "$bin\pg_restore.exe" --no-owner --no-acl --file=$sql $dump
        }
    }
    $prelude = Join-Path $DumpDir "prelude.sql"
    Set-Content -Path $prelude -Encoding ascii -Value @(
        "SET lock_timeout = '30s';",
        "SET client_min_messages = warning;",
        "DROP SCHEMA IF EXISTS public CASCADE;",
        "CREATE SCHEMA public;"
    )

    Log "Replacing local database in a single transaction"
    Invoke-Native "restore" {
        & "$bin\psql.exe" $LocalUrl --single-transaction -v ON_ERROR_STOP=1 -q `
            -f $prelude -f $sql | Out-Null
    }
    Remove-Item $sql, $prelude -Force

    Get-ChildItem $DumpDir -Filter "nflfp-*.dump" | Sort-Object Name -Descending |
        Select-Object -Skip $KeepDumps | Remove-Item -Force

    Log "Done. Local database now matches Railway $RailwayEnvironment as of $stamp."
}
catch {
    Log "FAILED: $($_.Exception.Message) - local database was left unchanged."
    exit 1
}
