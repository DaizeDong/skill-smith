<#
  fleet-verdict.ps1: read the verdict fleet_check.py writes and render it for a digest.

  The fleet verdict is documentation and conformance debt across the skill fleet. It is reported on
  its own and never feeds another task's exit code: a long SKILL.md must not read as a failed job.

    Resolve-FleetStatusPath  asks fleet_check.py (beside this file) where its status artifact is.
    Get-FleetVerdict         reads that artifact and reports freshness as a state of its own:
                             GREEN, AMBER, RED come from the artifact; STALE, MISSING, UNREADABLE
                             mean this reader could not get a current verdict.
    Format-FleetVerdictBlock renders the verdict as a labelled block that never says FAILED, always
                             names the artifact, and states GREEN out loud with its time and coverage,
                             so a missing block means the reader did not run.

  A caller that knows which run should have produced the artifact passes -NotOlderThan (that run's
  start); an age limit alone cannot tell "the run happened" from "an older artifact is still there".

  Stdlib PowerShell only. Dot-source it: . <skill-smith skill root>\scripts\fleet-verdict.ps1
#>

# The only verdicts the producer may write. STALE/MISSING/UNREADABLE are this reader's own reports, so
# an artifact claiming one of them is rejected rather than passed through.
$script:FleetProducerVerdicts = @('GREEN', 'AMBER', 'RED')
$script:FleetVerdictStates = @('GREEN', 'AMBER', 'RED', 'STALE', 'MISSING', 'UNREADABLE')

function Resolve-FleetStatusPath {
  param([string]$FleetScript = '', [string]$Python = '')
  if (-not $FleetScript) { $FleetScript = Join-Path $PSScriptRoot 'fleet_check.py' }
  if (-not $Python) { $Python = Join-Path $env:ProgramData 'miniconda3\python.exe' }
  if (-not (Test-Path -LiteralPath $FleetScript -PathType Leaf)) {
    throw 'fleet_check.py is not beside fleet-verdict.ps1'
  }
  $lines = @(& $Python $FleetScript --print-status-path 2>$null)
  if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1 -or -not [IO.Path]::IsPathRooted([string]$lines[0])) {
    throw 'fleet_check.py --print-status-path did not return one absolute path'
  }
  return [string]$lines[0]
}

# Resolved once at dot-source time; a failure leaves it empty and Get-FleetVerdict reports UNREADABLE.
$script:FleetStatusDefault = ''
try { $script:FleetStatusDefault = Resolve-FleetStatusPath } catch {}

function Get-FleetVerdict {
  <#
    .PARAMETER StatusPath
      The status JSON fleet_check.py writes; defaults to the path the tool itself reports.
    .PARAMETER MaxAgeHours
      Older than this and the answer is STALE.
    .PARAMETER NotOlderThan
      Start of the run the verdict must describe; an artifact stamped earlier is STALE.
    .PARAMETER FreshnessLabel
      That run in words, used in the STALE reason.
    .OUTPUTS
      PSCustomObject: State, Verdict, Digest, Utc, AgeHours, Reason, Attention (bool), Coverage, Path.
  #>
  param(
    [string]$StatusPath = $script:FleetStatusDefault,
    [double]$MaxAgeHours = 30,
    [datetime]$NotOlderThan = [datetime]::MinValue,
    [string]$FreshnessLabel = 'this run'
  )
  $coverage = ''
  $mk = {
    param($State, $Verdict, $Digest, $Utc, $Age, $Reason)
    [PSCustomObject]@{
      State     = $State
      Verdict   = $Verdict
      Digest    = $Digest
      Utc       = $Utc
      AgeHours  = $Age
      Reason    = $Reason
      Attention = ($State -ne 'GREEN')
      Coverage  = $coverage
      Path      = $StatusPath
    }
  }
  if (-not $StatusPath) {
    try { $StatusPath = Resolve-FleetStatusPath } catch {
      return & $mk 'UNREADABLE' '' '' '' $null 'fleet artifact path could not be resolved'
    }
  }
  if (-not (Test-Path -LiteralPath $StatusPath)) {
    return & $mk 'MISSING' '' '' '' $null "no fleet verdict artifact at $StatusPath; the fleet check has not run here"
  }
  try {
    $j = Get-Content -LiteralPath $StatusPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
  } catch {
    return & $mk 'UNREADABLE' '' '' '' $null "fleet verdict artifact is unreadable: $($_.Exception.Message)"
  }
  $utc = [string]$j.utc
  $age = $null
  try { $age = ((Get-Date).ToUniversalTime() - ([datetime]$utc).ToUniversalTime()).TotalHours } catch { $age = $null }
  $digest = [string]$j.digest
  $verdict = ([string]$j.verdict).ToUpper()
  try {
    if ($null -ne $j.coverage) {
      $ev = [int]$j.coverage.evaluated
      $ne = [int]$j.coverage.not_evaluated
      $tot = $ev + $ne
      if ($tot -gt 0) { $coverage = "{0} of {1} rows evaluated ({2:N0}%), {3} not evaluated" -f $ev, $tot, (100.0 * $ev / $tot), $ne }
    }
  } catch { $coverage = '' }
  if (-not $digest) { $digest = "(no digest field in the artifact; schema $($j.schema))" }
  if ($null -eq $age) {
    return & $mk 'UNREADABLE' $verdict $digest $utc $null "fleet verdict artifact has no readable utc timestamp"
  }
  if ($NotOlderThan -gt [datetime]::MinValue) {
    $cut = $NotOlderThan.ToUniversalTime()
    $art = $null
    try { $art = ([datetime]$utc).ToUniversalTime() } catch { $art = $null }
    if (($null -eq $art) -or ($art -lt $cut.AddSeconds(-5))) {
      return & $mk 'STALE' $verdict $digest $utc $age ("the fleet check did not produce an artifact for {0}: that run started {1:yyyy-MM-ddTHH:mm:ssZ}, and the newest artifact on disk is stamped {2}; what is on disk is a PREVIOUS run's verdict" -f $FreshnessLabel, $cut, $utc)
    }
  }
  if ($age -lt -0.1) {
    return & $mk 'UNREADABLE' $verdict $digest $utc $age ("fleet verdict is stamped {0}, which is {1:N1}h in the FUTURE; the artifact's clock or its producer is wrong, so its freshness cannot be judged" -f $utc, [Math]::Abs($age))
  }
  if ($age -gt $MaxAgeHours) {
    return & $mk 'STALE' $verdict $digest $utc $age ("fleet verdict is {0:N0}h old (limit {1:N0}h); it describes an earlier fleet" -f $age, $MaxAgeHours)
  }
  if ($script:FleetProducerVerdicts -notcontains $verdict) {
    return & $mk 'UNREADABLE' $verdict $digest $utc $age "unrecognized verdict '$verdict' in the artifact"
  }
  return & $mk $verdict $verdict $digest $utc $age ''
}

function Format-FleetVerdictBlock {
  <#
    .SYNOPSIS
      Render a fleet verdict as its own block. Returns an array of lines; empty only for a fresh GREEN
      when the caller passes -OmitWhenGreen.
  #>
  param(
    [Parameter(Mandatory = $true)]$Verdict,
    [switch]$OmitWhenGreen
  )
  if (-not $Verdict.Attention -and $OmitWhenGreen) { return @() }
  $head = switch ($Verdict.State) {
    'RED'        { "FLEET DOC DEBT: RED. Skill-repo conformance has failing rows." }
    'AMBER'      { "FLEET DOC DEBT: AMBER. Skill-repo conformance has warnings, no failures." }
    'GREEN'      { "FLEET DOC DEBT: GREEN. The check ran and nothing that was evaluated failed." }
    'STALE'      { "FLEET DOC DEBT: UNKNOWN, the verdict is stale. $($Verdict.Reason)" }
    'MISSING'    { "FLEET DOC DEBT: UNKNOWN, no verdict was produced. $($Verdict.Reason)" }
    'UNREADABLE' { "FLEET DOC DEBT: UNKNOWN, the verdict could not be read. $($Verdict.Reason)" }
    default      { "FLEET DOC DEBT: UNKNOWN state '$($Verdict.State)'." }
  }
  # An unobserved state quotes the artifact's sentence only as a labelled last-known value.
  $observed = ($script:FleetProducerVerdicts -contains $Verdict.State)
  $lines = @("[fleet] $head")
  if ($Verdict.Digest) {
    if ($observed) { $lines += "  $($Verdict.Digest)" }
    else           { $lines += "  last known (NOT current, do not act on it): $($Verdict.Digest)" }
  }
  if ($Verdict.Utc) {
    $when = if ($observed) { "  measured {0}{1}" } else { "  that last-known verdict was measured {0}{1}" }
    $lines += ($when -f $Verdict.Utc, $(if ($null -ne $Verdict.AgeHours) { " ({0:N0}h ago)" -f $Verdict.AgeHours } else { "" }))
  }
  if ($observed) {
    if ($Verdict.Coverage) { $lines += "  coverage: $($Verdict.Coverage)" }
    else { $lines += "  coverage: NOT STATED by the artifact, so how much of the fleet this verdict speaks for is unknown" }
  }
  if ($Verdict.State -eq 'GREEN') {
    $lines += "  Nothing to do. This line is printed even when clean on purpose: if the fleet"
    $lines += "  section is missing from a digest, the reader did not run, which is not this."
  } else {
    $lines += "  This is a documentation and conformance chore. It is NOT a backup problem and no"
    $lines += "  data is at risk."
  }
  $lines += "  Artifact: $($Verdict.Path)"
  return $lines
}
