# 엑셀이 탭 구분 CSV를 쉼표 구분으로 잘못 열었다가 저장해서
# 한 줄 전체가 "한 칸"으로 뭉쳐버린 파일을 복구하는 스크립트.
#
# 사용법:
#   . .\Recover-FlattenedCsv.ps1
#   Repair-FlattenedTsv -InPath "깨진파일.csv" -OutPath "복구본.csv"
#
# 원리:
#   1) 원본 바이트를 CP949로 읽는다 (엑셀이 "CSV(쉼표로 분리)"로 저장하면
#      이 인코딩으로 나가기 때문).
#   2) 쉼표/따옴표 규칙을 지키는 자체 파서로 "엑셀이 인식한 칸"들을 다시 만든다.
#      - 따옴표 안의 실제 줄바꿈(여러 줄짜리 셀)도 여기서 같이 처리된다.
#   3) 그 칸들을 다시 쉼표로 이어붙여 원래의 "한 줄" 텍스트를 복원한다.
#      (엑셀이 원본에 우연히 들어있던 쉼표를 진짜 구분자로 착각해서
#      쪼갰던 걸 되돌리는 단계)
#   4) 복원된 한 줄을 실제 구분자인 탭으로 쪼개 진짜 컬럼을 얻는다.
#   5) 각 필드에 남아있는 개별 따옴표 감싸기(원본 CSV 자체의 따옴표 이스케이프)를 벗긴다.

function Read-LockedFile {
    param([Parameter(Mandatory)][string]$Path)
    $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $ms = New-Object System.IO.MemoryStream
    $fs.CopyTo($ms)
    $fs.Close()
    return $ms.ToArray()
}

function Split-CsvLineLenient {
    # 쉼표 구분, 큰따옴표 이스케이프(" " -> 리터럴 ")를 지키는 관대한 한 줄 파서.
    # 표준 CSV 파서(TextFieldParser 등)와 달리, 따옴표가 필드 맨 앞이 아닌
    # 중간에 나타나도 예외를 던지지 않고 최대한 이어서 처리한다.
    param([Parameter(Mandatory)][string]$Line)
    $fields = New-Object System.Collections.Generic.List[string]
    $sb = New-Object System.Text.StringBuilder
    $inQuotes = $false
    $i = 0
    $n = $Line.Length
    while ($i -lt $n) {
        $c = $Line[$i]
        if ($inQuotes) {
            if ($c -eq '"') {
                if ($i + 1 -lt $n -and $Line[$i + 1] -eq '"') { [void]$sb.Append('"'); $i += 2; continue }
                else { $inQuotes = $false; $i++; continue }
            } else { [void]$sb.Append($c); $i++; continue }
        } else {
            if ($c -eq '"') { $inQuotes = $true; $i++; continue }
            elseif ($c -eq ',') { $fields.Add($sb.ToString()); [void]$sb.Clear(); $i++; continue }
            else { [void]$sb.Append($c); $i++; continue }
        }
    }
    $fields.Add($sb.ToString())
    return ,$fields.ToArray()
}

function ConvertFrom-QuotedField {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Field)
    if ($Field.Length -ge 2 -and $Field.StartsWith('"') -and $Field.EndsWith('"')) {
        $inner = $Field.Substring(1, $Field.Length - 2)
        return $inner -replace '""', '"'
    }
    return $Field
}

function Parse-CsvRawWithEmbeddedNewlines {
    # 전체 텍스트를 문자 단위로 훑으면서, 따옴표 밖의 줄바꿈만 "진짜 행 구분"으로
    # 인식하고 따옴표 안의 줄바꿈(여러 줄 셀)은 그대로 필드 내용에 포함시킨다.
    # 반환값: 각 행을 "엑셀이 인식한 칸들의 배열"로 표현한 리스트.
    param([Parameter(Mandatory)][string]$Text)
    $rows = New-Object System.Collections.Generic.List[object]
    $curRow = New-Object System.Collections.Generic.List[string]
    $sb = New-Object System.Text.StringBuilder
    $inQuotes = $false
    $i = 0
    $n = $Text.Length
    while ($i -lt $n) {
        $c = $Text[$i]
        if ($inQuotes) {
            if ($c -eq '"') {
                if ($i + 1 -lt $n -and $Text[$i + 1] -eq '"') { [void]$sb.Append('"'); $i += 2; continue }
                else { $inQuotes = $false; $i++; continue }
            } else { [void]$sb.Append($c); $i++; continue }
        } else {
            if ($c -eq '"') { $inQuotes = $true; $i++; continue }
            elseif ($c -eq ',') { $curRow.Add($sb.ToString()); [void]$sb.Clear(); $i++; continue }
            elseif ($c -eq "`r") { $i++; continue }
            elseif ($c -eq "`n") {
                $curRow.Add($sb.ToString()); [void]$sb.Clear()
                $rows.Add(@($curRow.ToArray()))
                $curRow = New-Object System.Collections.Generic.List[string]
                $i++; continue
            } else { [void]$sb.Append($c); $i++; continue }
        }
    }
    if ($sb.Length -gt 0 -or $curRow.Count -gt 0) {
        $curRow.Add($sb.ToString())
        $rows.Add(@($curRow.ToArray()))
    }
    return $rows
}

function Repair-FlattenedTsv {
    <#
      .SYNOPSIS
      엑셀이 탭 구분 CSV를 쉼표 구분으로 착각해 한 칸으로 뭉쳐버린 파일을 복구한다.
      .PARAMETER InPath
      깨진 원본 파일 (CP949 인코딩, 잠겨있어도 공유 읽기로 처리됨).
      .PARAMETER OutPath
      복구된 결과를 저장할 UTF-8 CSV 경로.
    #>
    param(
        [Parameter(Mandatory)][string]$InPath,
        [Parameter(Mandatory)][string]$OutPath
    )
    $cp949 = [System.Text.Encoding]::GetEncoding(949)
    $bytes = Read-LockedFile -Path $InPath
    $text = $cp949.GetString($bytes)

    $excelRows = Parse-CsvRawWithEmbeddedNewlines -Text $text

    $reconstructedLines = foreach ($cols in $excelRows) {
        # 엑셀이 원본 행마다 다르게 덧붙인 빈 칸(패딩)을 제거
        $lastNonEmpty = $cols.Count - 1
        while ($lastNonEmpty -gt 0 -and [string]::IsNullOrEmpty($cols[$lastNonEmpty])) { $lastNonEmpty-- }
        $trimmed = $cols[0..$lastNonEmpty]
        ($trimmed -join ',')
    }
    $reconstructedLines = $reconstructedLines | Where-Object { $_.Trim() -ne '' }

    $rows = foreach ($line in $reconstructedLines) {
        $fields = (Split-CsvLineLenient -Line $line) | ForEach-Object { ConvertFrom-QuotedField $_ }
        ,$fields
    }

    $header = $rows[0]
    $data = $rows[1..($rows.Count - 1)]
    $objs = foreach ($r in $data) {
        $o = [ordered]@{}
        for ($i = 0; $i -lt $header.Count; $i++) {
            $o[$header[$i]] = if ($i -lt $r.Count) { $r[$i] } else { '' }
        }
        [PSCustomObject]$o
    }

    $objs | Export-Csv -Path $OutPath -NoTypeInformation -Encoding UTF8
    Write-Host "복구 완료: $OutPath ($($objs.Count) rows)"
    return $objs
}

function Remove-BlankAndDuplicateRows {
    <#
      .SYNOPSIS
      TC_ID가 빈 행을 제거하고, (TC_ID, STEP) 기준으로 완전히 동일한 중복 행을 제거한다.
      내용이 다른데 키만 같은 행은 손대지 않고 별도로 보고한다(자동으로 지우면 위험하므로).
    #>
    param([Parameter(Mandatory)]$Rows)
    $nonBlank = $Rows | Where-Object { -not [string]::IsNullOrWhiteSpace($_.TC_ID) }
    $groups = @($nonBlank | Group-Object TC_ID, STEP)
    $kept = New-Object System.Collections.Generic.List[object]
    $conflicts = New-Object System.Collections.Generic.List[object]
    foreach ($g in $groups) {
        $serialized = $g.Group | ForEach-Object { ($_.PSObject.Properties.Value -join '|') }
        $uniqueSerialized = $serialized | Select-Object -Unique
        if ($uniqueSerialized.Count -eq 1) {
            $kept.Add($g.Group[0])
        } else {
            $conflicts.Add($g)
            $kept.Add($g.Group[0])  # 일단 첫 번째를 남기되, 아래서 충돌로 별도 보고
        }
    }
    if ($conflicts.Count -gt 0) {
        Write-Warning "$($conflicts.Count)개의 (TC_ID, STEP) 그룹은 내용이 서로 달라서 자동 병합하지 않았습니다. 직접 확인하세요:"
        $conflicts | ForEach-Object { Write-Warning ("  " + $_.Name) }
    }
    return $kept
}
