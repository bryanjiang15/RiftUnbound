param(
	[switch]$List,
	[Parameter(ValueFromRemainingArguments = $true)]
	[string[]]$Suites
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path

$candidates = @()
if ($env:GODOT) { $candidates += $env:GODOT }
$candidates += @(
	"C:\Users\t-bryanjiang\AppData\Local\Programs\Godot\godot_console.exe",
	"C:\Users\t-bryanjiang\AppData\Local\Programs\Godot\godot.exe",
	"godot_console.exe",
	"godot"
)

$godot = $null
foreach ($candidate in $candidates) {
	if (-not [string]::IsNullOrWhiteSpace($candidate)) {
		$cmd = Get-Command $candidate -ErrorAction SilentlyContinue
		if ($cmd) {
			$godot = $cmd.Source
			break
		}
		if (Test-Path $candidate) {
			$godot = $candidate
			break
		}
	}
}

if (-not $godot) {
	throw "Godot executable not found. Set GODOT env var or install godot_console.exe in PATH."
}

$args = @(
	"--headless",
	"--path", $repoRoot,
	"--script", "res://Scripts/Tests/Tcg/TcgTestRunner.gd",
	"--"
)

if ($List) {
	$args += "--list"
} elseif ($Suites -and $Suites.Count -gt 0) {
	$args += $Suites
}

& $godot @args
exit $LASTEXITCODE
