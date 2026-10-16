"""
검증용 가짜 로그 생성기.

룰을 수정한 뒤 실제 장비 없이 판정 로직을 확인할 때 쓴다.
    python tools/make_test_log.py > logs/sample.log
    python main.py --replay logs/sample.log --all
"""
import sys
from datetime import datetime, timedelta

START = datetime(2026, 7, 22, 10, 46, 32)
RED = "\x1b[1;31m"
RST = "\x1b[0m"

# (경과초, 라인)
LINES = [
    (0.0,  "U-Boot 2019.04 (Jul 10 2026 - 11:20:33 +0900)"),
    (0.5,  "Autobooting in 1 seconds"),
    (1.4,  "Starting kernel ..."),
    (3.2,  "mmcblk0: p1"),
    (4.0,  "dvr: (IntProbe) DISK_INFO : DISK[sata0] 1000GB"),
    (5.1,  "dvr: (EmmcProbe) mmc1 finished probe()"),
    (6.0,  f"{RED}dvr: (LogWriter) MOUNT(SD) ok{RST}"),   # ANSI 섞임
    (8.0,  "dvr: (LogWriter) BOOT COMPLETE"),             # TC002 PASS
    (9.0,  "dvr: (LogWriter) Ignition changed 0 -> 1"),
    (10.0, "dvr: (LogWriter) RECORD ON(SD)"),
    (11.0, "dvr: (RecDrv) @@@ Create File: /mnt/sd/20260722_1046.drv"),
    (12.0, "dvr: (RecExt) @@@ Create File: /mnt/sd/20260722_1046_ext.mdt"),

    # TC001 정상 (GSNR -> UploadEvent -> 200)
    (20.0, "dvr: (net_dms4) GSNR EVENT OCCURE"),
    (21.2, "http request url=[http://gwa.example.com:5000/UploadEvent]"),
    (23.9, "http status code [200]"),

    # TC001 실패 (500 응답)
    (40.0, "dvr: (net_dms4) GSNR EVENT OCCURE"),
    (41.0, "http request url=[http://gwa.example.com:5000/UploadEvent]"),
    (43.5, "http status code [500]"),

    # TC001 타임아웃 (요청 후 응답 없음)
    (60.0, "dvr: (net_dms4) GSNR EVENT OCCURE"),
    (61.0, "http request url=[http://gwa.example.com:5000/UploadEvent]"),
    (63.0, "dvr: (net_dms4) socket recv timeout"),
    (80.0, "dvr: (net_dms4) retry scheduled"),
    (90.0, "dvr: (LogWriter) RECORD OFF(SD)"),

    # 이벤트류
    (95.0, "dvr: (DSM) DSM Event: DROWSINESS2"),
    (96.0, "dvr: (ADAS) ADAS Event: PCW"),
    (97.0, "dvr: (LogWriter) RTC LOW BATTERY"),

    # TC026 회귀 (probe stuck)
    (100.0, "dvr: (IntProbe) Disk probe is not finished yet!!"),

    # SD 포맷
    (110.0, "dvr: (osd) Format start!!"),
    (135.0, "dvr: DISK[mmc0] format end"),
    (140.0, "dvr: (LogWriter) RECORD ON(SD)"),
]


def main():
    out = sys.stdout
    for offset, text in LINES:
        ts = START + timedelta(seconds=offset)
        out.write(f"[{ts.strftime('%H:%M:%S.%f')[:-3]}] {text}\n")


if __name__ == "__main__":
    main()
