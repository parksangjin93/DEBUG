# Jira 이슈 키로 GitLab 커밋을 찾고, 그 커밋의 diff에서
# 로그/디버그 출력 문자열 후보를 뽑아내는 스크립트.
#
# 전제: gitlab-smartets 스킬의 gitlab.ps1이 먼저 dot-source 되어 있어야 함.
#   . "$env:USERPROFILE\.claude\skills\gitlab-smartets\scripts\gitlab.ps1"
#
# 주의 (이번에 직접 겪은 것들):
#   - GitLab 인스턴스의 /repository/commits?search=... 파라미터가 이 서버에서는
#     필터링을 안 한다(버그로 추정). 전체 커밋을 받아와서 우리가 직접
#     문자열로 걸러야 한다.
#   - /projects/:id/search (scope=commits, scope=blobs)도 Advanced Search가
#     꺼져있어서 0건만 돌려준다.
#   - 그래서 이 스크립트는 전체 커밋 목록을 한 번 받아서 로컬에 캐시해두고
#     (Get-AllCommitsCached), 그 안에서 정규식으로 검색한다.
#   - 커밋을 찾아도 diff에 실제 로그 문자열이 없는 경우가 많다(로직/설정 수정).
#     또한 코드의 dbg_info()/printf() 로그가 TC 자동화가 실제로 읽는 로그
#     파일과 같은 경로인지는 보장 안 됨 -> 후보일 뿐, 기기 로그로 재검증 필요.

function Get-AllCommitsCached {
    <#
      .SYNOPSIS
      프로젝트의 전체 커밋 이력을 받아와 로컬 JSON 파일에 캐시한다.
      이미 캐시가 있으면 그걸 재사용한다 (-Force로 강제 재수집).
    #>
    param(
        [Parameter(Mandatory)][int]$ProjectId,
        [string]$CachePath = (Join-Path $env:TEMP "gitlab_commits_$ProjectId.json"),
        [switch]$Force
    )
    if ((Test-Path $CachePath) -and -not $Force) {
        Write-Host "캐시 사용: $CachePath"
        return Get-Content $CachePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $page = 1
    $all = @()
    do {
        $batch = Invoke-GitLabApi -Path "/projects/$ProjectId/repository/commits" -Query @{ all = "true"; per_page = 100; page = $page }
        $all += $batch
        $page++
    } while ($batch.Count -eq 100)
    Write-Host "전체 커밋 $($all.Count)건 수집 (범위: $($all[-1].created_at) ~ $($all[0].created_at))"
    $all | ConvertTo-Json -Depth 5 | Set-Content -Path $CachePath -Encoding UTF8
    return $all
}

function Find-CommitsByJiraKey {
    <#
      .SYNOPSIS
      캐시된 커밋 목록에서 Jira 키(예: IX-556)를 단어 경계로 검색한다.
      "IX-1"이 "IX-160"에 잘못 매칭되지 않도록 경계를 둔다.
    #>
    param(
        [Parameter(Mandatory)]$AllCommits,
        [Parameter(Mandatory)][string[]]$Keys
    )
    $resultsMap = @{}
    foreach ($k in $Keys) {
        $pattern = "(^|\D)$([regex]::Escape($k))(\D|$)"
        $resultsMap[$k] = @($AllCommits | Where-Object { $_.title -match $pattern })
    }
    return $resultsMap
}

function Get-CommitLogStringCandidates {
    <#
      .SYNOPSIS
      커밋 하나의 diff를 받아, 추가된(+) 줄 중 따옴표를 포함한 로그성 라인만 뽑는다.
      dbg_info/dbg_error/printf/LOG/syslog/LogWriter 등 흔한 로그 매크로 이름을 우선한다.
    #>
    param(
        [Parameter(Mandatory)][int]$ProjectId,
        [Parameter(Mandatory)][string]$Sha
    )
    $diff = Invoke-GitLabApi -Path "/projects/$ProjectId/repository/commits/$Sha/diff"
    # PowerShell이 배열을 이상하게 감쌀 때가 있어서 .value로 한 번 더 확인
    $files = if ($diff.value) { $diff.value } else { $diff }

    $candidates = foreach ($file in $files) {
        $addedLines = ($file.diff -split "`n") | Where-Object { $_.StartsWith('+') -and -not $_.StartsWith('+++') }
        $logLines = $addedLines | Where-Object { $_ -match '"' }
        foreach ($line in $logLines) {
            [PSCustomObject]@{
                file = $file.new_path
                line = $line.TrimStart('+', "`t", ' ')
                looksLikeLogMacro = [bool]($line -match '(dbg_info|dbg_error|printf|LOG|syslog|LogWriter|_log|Log\()')
            }
        }
    }
    return $candidates
}

<#
  .EXAMPLE 사용 순서 (IX3000 = ithaca repo, project id 177)

  . "$env:USERPROFILE\.claude\skills\gitlab-smartets\scripts\gitlab.ps1"
  . ".\Search-GitLabJiraCommits.ps1"

  $all = Get-AllCommitsCached -ProjectId 177
  $keys = @("IX-44","IX-65", ...)
  $found = Find-CommitsByJiraKey -AllCommits $all -Keys $keys

  foreach ($k in $keys) {
      if ($found[$k].Count -gt 0) {
          $sha = $found[$k][0].id
          $cands = Get-CommitLogStringCandidates -ProjectId 177 -Sha $sha
          $cands | Where-Object looksLikeLogMacro | Format-Table file, line -AutoSize
      }
  }
#>
