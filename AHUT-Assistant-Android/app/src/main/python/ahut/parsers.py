"""HTML 解析：课表 / 成绩 / 考试。

正方教务系统不同版本页面结构略有差异，这里采用「先按标准结构解析，
失败再退化到通用表格解析」的策略，尽量不因小改动整体失效。
"""
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]
WEEKDAY_ALIASES = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7,
}


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def cell_text(el: Tag) -> str:
    """把单元格内容转为文本，<br> 变行、去多余空白。"""
    for br in el.find_all("br"):
        br.replace_with("\n")
    text = el.get_text("\n")
    lines = [re.sub(r"[ \t\u3000]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join([ln for ln in lines if ln])


def _span(tag: Tag, attr: str, default: int = 1) -> int:
    try:
        return max(1, int(tag.get(attr) or default))
    except (TypeError, ValueError):
        return default


def build_matrix(table: Tag) -> list[list[Tag | None]]:
    """展开 rowspan/colspan，得到二维表格。"""
    rows = table.find_all("tr")
    matrix: list[list[Tag | None]] = []
    occupied: dict[tuple[int, int], Tag] = {}
    for r, tr in enumerate(rows):
        while len(matrix) <= r:
            matrix.append([])
        col = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while (r, col) in occupied:
                matrix[r].append(occupied[(r, col)])
                col += 1
            rowspan = _span(cell, "rowspan")
            colspan = _span(cell, "colspan")
            for dr in range(rowspan):
                for dc in range(colspan):
                    rr, cc = r + dr, col + dc
                    while len(matrix) <= rr:
                        matrix.append([])
                    while len(matrix[rr]) <= cc:
                        matrix[rr].append(None)
                    matrix[rr][cc] = cell
                    if dr or dc:
                        occupied[(rr, cc)] = cell
            col += colspan
    width = max((len(row) for row in matrix), default=0)
    for row in matrix:
        row.extend([None] * (width - len(row)))
    return matrix


# ------------------------- 课表 -------------------------

def parse_weeks(text: str) -> list[int]:
    """解析周次描述，如 "1-16周" / "1-8周,10-16周" / "单周"。"""
    if not text:
        return []
    t = text.replace("，", ",").replace("至", "-").replace("—", "-")
    weeks: set[int] = set()
    for seg in re.split(r"[,、;；\s]+", t):
        if not seg:
            continue
        single = "单" in seg
        double = "双" in seg
        nums = re.findall(r"\d+", seg)
        if len(nums) >= 2:
            a, b = int(nums[0]), int(nums[1])
            if a > b:
                a, b = b, a
            for w in range(a, b + 1):
                if single and w % 2 == 0:
                    continue
                if double and w % 2 == 1:
                    continue
                weeks.add(w)
        elif len(nums) == 1:
            weeks.add(int(nums[0]))
    return sorted(weeks)


def _font_value(cell: Tag, title: str) -> str:
    for font in cell.find_all("font"):
        if title in (font.get("title") or ""):
            return font.get_text(" ", strip=True)
    return ""


def parse_course_cell(cell: Tag) -> dict[str, Any] | None:
    raw = cell_text(cell)
    if not raw or raw in ("-", "无"):
        return None
    teacher = _font_value(cell, "教师") or _font_value(cell, "老师")
    weeks_txt = _font_value(cell, "周次") or _font_value(cell, "时间")
    place = _font_value(cell, "地点") or _font_value(cell, "教室")
    # 清理掉 font 内容后的主文本行
    text_only = cell_text(cell)
    lines = [ln for ln in text_only.split("\n") if ln]
    name = lines[0] if lines else raw
    if not teacher:
        for ln in lines[1:]:
            if re.search(r"周", ln):
                continue
            if re.search(r"[楼栋室馆中心]|\d{3}|东\d|西\d|南\d|北\d", ln):
                place = place or ln
            elif len(ln) <= 12:
                teacher = teacher or ln
    if not place:
        for ln in lines[1:]:
            if re.search(r"楼|室|馆|中心|^[A-Z]?\d", ln):
                place = ln
                break
    if not weeks_txt:
        for ln in lines[1:]:
            if "周" in ln:
                weeks_txt = ln
                break
    return {
        "name": re.sub(r"\(.*?\)|（.*?）$", "", name).strip(),
        "teacher": teacher,
        "place": place,
        "weeks_text": weeks_txt,
        "weeks": parse_weeks(weeks_txt),
    }


def parse_timetable(html: str) -> dict[str, Any]:
    doc = soup(html)
    table = doc.find("table", id="kbtable") or doc.find("table", class_=re.compile("kbtable|Nsb_r_list"))
    if table is None:
        # 退化：找含「星期一」且单元格较多的表
        for t in doc.find_all("table"):
            if "星期一" in t.get_text() and len(t.find_all("td")) > 20:
                table = t
                break
    if table is None:
        return {"courses": [], "grid": [], "periods": [], "adapted": False}

    matrix = build_matrix(table)

    # 找到星期表头列位置
    day_col = {}
    for row in matrix[:3]:
        for idx, cell in enumerate(row):
            if cell is None:
                continue
            txt = cell.get_text(" ", strip=True)
            m = re.search(r"星期([一二三四五六日天])", txt)
            if m:
                day_col[WEEKDAY_ALIASES[m.group(1)]] = idx
        if len(day_col) >= 5:
            break
    first_day_col = min(day_col.values()) if day_col else 1

    courses: list[dict[str, Any]] = []
    for r, row in enumerate(matrix):
        label = ""
        if row and row[0] is not None:
            label = row[0].get_text(" ", strip=True)
        for c, cell in enumerate(row):
            if cell is None or c < first_day_col:
                continue
            # 安工大版本：课程内容在 td 内 class="kbcontent1" / "kbcontent" 的 div 里
            blocks = cell.find_all(class_=re.compile(r"kbcontent"))
            if not any(b.get_text(strip=True) for b in blocks):
                continue
            info = parse_course_cell(cell)
            if not info:
                continue
            weekday = None
            for day, col in day_col.items():
                if col == c:
                    weekday = day
                    break
            if weekday is None:
                weekday = c - first_day_col + 1
            if not 1 <= weekday <= 7:
                continue
            period = _period_from_label(label)
            if not period:
                period = max(1, r)  # 表头占第 0 行，body 行号即大节序号
            # 归一到「每大节起始节次」：1/3/5/7/9/11
            period = ((period - 1) // 2) * 2 + 1
            info.update({"weekday": weekday, "period": period,
                         "row": r, "col": c})
            courses.append(info)

    if not courses:
        return {"courses": [], "grid": [], "periods": [], "adapted": False}
    periods = sorted({c["period"] for c in courses if c.get("period")})
    return {"courses": courses, "periods": periods, "adapted": True}


CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _period_from_label(label: str) -> int:
    """把「第1节 / 1-2节 / 第一大节 / 第二大节」转成起始节次。"""
    label = label or ""
    m = re.search(r"(\d+)", label)
    if m:
        return int(m.group(1))
    m = re.search(r"第([一二三四五六七八九十]+)", label)
    if m:
        n = CN_DIGITS.get(m.group(1)[0], 0)
        if n and "大节" in label:
            return n * 2 - 1
        return n
    return 0


# ------------------------- 通用表格 -------------------------

def table_to_records(table: Tag) -> tuple[list[str], list[list[str]]]:
    matrix = build_matrix(table)
    if not matrix:
        return [], []
    headers = []
    header_row = 0
    for i, row in enumerate(matrix[:3]):
        texts = [(cell.get_text(" ", strip=True) if cell else "") for cell in row]
        if sum(1 for t in texts if t) >= max(3, len(row) // 2):
            headers, header_row = texts, i
            break
    records = []
    for row in matrix[header_row + 1:]:
        records.append([(cell.get_text(" ", strip=True) if cell else "") for cell in row])
    return headers, records


def _pick(keywords: list[str], headers: list[str]) -> int:
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw in h:
                return i
    return -1


def parse_grades(html: str) -> dict[str, Any]:
    doc = soup(html)
    best = None
    for table in doc.find_all("table"):
        headers, records = table_to_records(table)
        joined = "".join(headers)
        if "成绩" in joined and re.search(r"课程|学分", joined):
            best = (headers, records)
            break
    if not best:
        return {"items": [], "adapted": False}

    headers, records = best
    idx_name = _pick(["课程名称", "课程名", "课程"], headers)
    idx_credit = _pick(["学分"], headers)
    idx_score = _pick(["成绩", "分数"], headers)
    idx_point = _pick(["绩点"], headers)
    idx_nature = _pick(["课程性质", "性质", "课程类别"], headers)
    idx_term = _pick(["学期", "开课学期"], headers)
    idx_exam = _pick(["考试性质", "考核方式"], headers)

    items = []
    for rec in records:
        def get(i):
            return rec[i].strip() if 0 <= i < len(rec) else ""
        name = get(idx_name)
        if not name or name in ("课程名称",):
            continue
        score = get(idx_score)
        point = get(idx_point)
        items.append({
            "name": name,
            "credit": _to_float(get(idx_credit)),
            "score": score,
            "point": _to_float(point),
            "nature": get(idx_nature),
            "term": get(idx_term),
            "exam_type": get(idx_exam),
        })

    return {"items": items, "adapted": bool(items), "headers": headers}


def _to_float(text: str) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def parse_exams(html: str) -> dict[str, Any]:
    doc = soup(html)
    for table in doc.find_all("table"):
        headers, records = table_to_records(table)
        joined = "".join(headers)
        if not (re.search(r"考试", joined) and re.search(r"时间|考场|地点", joined)):
            continue
        idx_name = _pick(["课程名称", "课程"], headers)
        idx_time = _pick(["考试时间", "时间"], headers)
        idx_place = _pick(["考场", "地点", "教室"], headers)
        idx_seat = _pick(["座位"], headers)
        idx_form = _pick(["考试形式", "考核方式"], headers)
        items = []
        for rec in records:
            def get(i):
                return rec[i].strip() if 0 <= i < len(rec) else ""
            name = get(idx_name)
            if not name or name in ("课程名称", "未查询到数据", "无"):
                continue
            if get(idx_time) in ("未查询到数据",) and get(idx_place) in ("未查询到数据",):
                continue
            items.append({
                "name": name,
                "time": get(idx_time),
                "place": get(idx_place),
                "seat": get(idx_seat),
                "form": get(idx_form),
            })
        return {"items": items, "adapted": True}
    if "未查询到数据" in (html or ""):
        return {"items": [], "adapted": True}
    return {"items": [], "adapted": False}


def parse_student(html: str) -> dict[str, str]:
    doc = soup(html)
    text = doc.get_text(" ", strip=True)
    info = {}
    m = re.search(r"姓名[：:\s]*([\u4e00-\u9fa5]{2,6})", text)
    if m:
        info["name"] = m.group(1)
    m = re.search(r"学号[：:\s]*(\d{6,20})", text) \
        or re.search(r'xs0101id\s*=\s*"(\d{6,20})"', html or "")
    if m:
        info["id"] = m.group(1)
    return info
