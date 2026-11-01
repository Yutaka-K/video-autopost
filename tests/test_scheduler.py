import xml.etree.ElementTree as ET
from pathlib import Path

from autopost.scheduler import build_task_xml

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def parse(xml: str):
    return ET.fromstring(xml.split("?>", 1)[1])


def test_hourly_xml():
    root = parse(build_task_xml(Path(r"C:\Users\たろう\動画 投稿"), Path(r"C:\x\pythonw.exe"), user="PC\\たろう"))
    assert root.find(".//t:Repetition/t:Interval", NS).text == "PT1H"
    assert root.find(".//t:Exec/t:Command", NS).text == r"C:\x\pythonw.exe"
    args = root.find(".//t:Exec/t:Arguments", NS).text
    assert args.endswith("run.py\" run --auto") and args.startswith('"')
    assert root.find(".//t:WorkingDirectory", NS).text == r"C:\Users\たろう\動画 投稿"
    assert root.find(".//t:StartWhenAvailable", NS).text == "true"


def test_daily_xml():
    root = parse(build_task_xml(Path("C:/a"), Path("C:/p.exe"), mode="daily", time_hhmm="7:30", user="u"))
    assert root.find(".//t:Repetition", NS) is None
    assert root.find(".//t:StartBoundary", NS).text.endswith("T07:30:00")
