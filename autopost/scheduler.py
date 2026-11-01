"""Windows のタスクスケジューラに「自動実行」を登録・解除する処理。"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "動画自動投稿ツール"


def python_for_task() -> Path:
    """黒い画面を出さずに動かすため pythonw.exe を優先して使う。"""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return pythonw if pythonw.exists() else exe


def build_task_xml(base_dir: Path, python_exe: Path, mode: str = "hourly", time_hhmm: str = "09:00",
                   user: str | None = None) -> str:
    """タスクの設定（XML）を作る。

    mode = "hourly" … 1時間ごとに実行（投稿日時のズレは最大1時間）
    mode = "daily"  … 毎日 time_hhmm に1回実行
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if mode == "daily":
        hh, mm = time_hhmm.split(":")
        trigger = f"""    <CalendarTrigger>
      <StartBoundary>{today}T{int(hh):02d}:{int(mm):02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>"""
    else:
        trigger = f"""    <CalendarTrigger>
      <Repetition>
        <Interval>PT1H</Interval>
        <Duration>P1D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{today}T00:05:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>"""
    user = user or f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    script = base_dir / "run.py"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>投稿待ちフォルダの動画を、指定日時にSNSへ自動投稿します。</Description>
  </RegistrationInfo>
  <Triggers>
{trigger}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(python_exe))}</Command>
      <Arguments>{escape(f'"{script}" run --auto')}</Arguments>
      <WorkingDirectory>{escape(str(base_dir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def register(base_dir: Path, mode: str = "hourly", time_hhmm: str = "09:00") -> bool:
    if os.name != "nt":
        print("この機能は Windows でだけ使えます。")
        return False
    xml = build_task_xml(base_dir, python_for_task(), mode, time_hhmm)
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(xml)
        xml_path = f.name
    try:
        proc = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_path, "/F"],
            capture_output=True, text=True, encoding="cp932", errors="replace",
        )
    finally:
        os.unlink(xml_path)
    if proc.returncode == 0:
        if mode == "daily":
            print(f"登録しました！ 毎日 {time_hhmm} に自動で実行されます。")
        else:
            print("登録しました！ 1時間ごとに自動で実行されます。")
        print("パソコンの電源が切れていた場合は、次に電源を入れたときに実行されます。")
        print(f"（確認・削除は「タスク スケジューラ」アプリの「{TASK_NAME}」から行えます）")
        return True
    print("登録に失敗しました。")
    print(proc.stdout + proc.stderr)
    return False


def unregister() -> bool:
    if os.name != "nt":
        print("この機能は Windows でだけ使えます。")
        return False
    proc = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                          capture_output=True, text=True, encoding="cp932", errors="replace")
    if proc.returncode == 0:
        print("自動実行の登録を解除しました。")
        return True
    print("解除できませんでした（登録されていない可能性があります）。")
    print(proc.stdout + proc.stderr)
    return False
