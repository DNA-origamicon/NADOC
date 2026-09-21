# Optional Windows launcher: owns a narrowly scoped temporary firewall rule.
# Run in an Administrator PowerShell if ordinary LAN access is blocked.
param(
    [string]$Package,
    [string]$ControlFile,
    [Parameter(Mandatory=$true)][string]$BindAddress,
    [int]$Port = 5182,
    [int]$Minutes = 120,
    [string]$Dist = (Join-Path $PSScriptRoot '..\frontend\dist')
)
$ErrorActionPreference = 'Stop'
$node = (Get-Command node.exe).Source
$hostScript = Join-Path $PSScriptRoot 'prepared_view_host.mjs'
$ruleName = 'NADOC-Temporary-Viewer-' + [guid]::NewGuid().ToString('N')
$created = $false
$child = $null
try {
    New-NetFirewallRule -Name $ruleName -DisplayName 'NADOC temporary prepared viewer' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -LocalAddress $BindAddress -RemoteAddress LocalSubnet -Program $node -Profile Any | Out-Null
    $created = $true
    $hostArgs = @($hostScript, '--dist', $Dist, '--bind', $BindAddress, '--port', $Port, '--minutes', $Minutes)
    if ($Package) { $hostArgs += @('--package', $Package) }
    if ($ControlFile) { $hostArgs += @('--control-file', $ControlFile) }
    # Keep native stdout off the interactive console: console selection/transcript
    # handling must never block the Node event loop serving viewers.
    $logBase = if ($ControlFile) { $ControlFile } else { Join-Path $env:TEMP $ruleName }
    $quotedArgs = ($hostArgs | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }) -join ' '
    $child = Start-Process -FilePath $node -ArgumentList $quotedArgs -PassThru `
        -RedirectStandardOutput ($logBase + '.stdout.log') -RedirectStandardError ($logBase + '.stderr.log')
    Write-Host "NADOC sharing host running on $BindAddress`:$Port for up to $Minutes minutes. Use Help > Share link."
    while (!$child.WaitForExit(1000)) { }
    if ($child.ExitCode -ne 0) { Get-Content ($logBase + '.stderr.log') -ErrorAction SilentlyContinue }

} finally {
    if ($child -and !$child.HasExited) { Stop-Process -Id $child.Id -ErrorAction SilentlyContinue }
    if ($ControlFile) { Remove-Item $ControlFile -ErrorAction SilentlyContinue }
    if ($created) { Remove-NetFirewallRule -Name $ruleName }
}
