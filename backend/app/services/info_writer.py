"""
CSP DocMaker — the app corrects INFO's AO / RBO itself (No. 153)

Asked 27 Oct 2026: "the app can change the INFO sheet by itself" — fully
automatic. When people corrected the AO or RBO Name INFO gave to two or more
CSPs, the same way (loop 1's suggestion), the app fixes INFO's AO block:

  * Only the corrected CSPs' BRANCHES move. An AO-block row lists several
    branches ("BODH GAYA, SHERGHATI"); changing the whole row's AO would make
    the other branches wrong. So each corrected branch is taken out of the
    row that gave the wrong value and put into a row of the same State and
    District that gives the right one — an existing row if there is one,
    else a new row copied from the old one with the AO (or RBO) changed and
    the District left blank (so the district's other, unlisted branches
    keep their one AO / RBO).
  * A CSP matched by DISTRICT (its branch is not listed) gets its branch
    listed on such a row, so it is matched by branch from then on; other
    branches of that district are not touched.

It does nothing — and says why — when a branch is listed twice in the
State, when INFO no longer gives the wrong value (someone fixed it), or when
a corrected CSP has no branch name. Every cell it changes is returned
(where, before, after) and kept on the suggestion, so it can be undone.

plan() is pure (rows in, changes out); apply() writes them.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.services.info_directory import (ASM, AO_COLUMNS, BLOCK_HEADERS,
                                         COLUMN_ALIASES, DC, normalize,
                                         place_key)

logger = logging.getLogger(__name__)

# No. 154: a person's own email / phone — the same person, just their
# details — corrected on 2+ CSPs the same way is changed in their INFO row.
PEOPLE_FIELDS = {"dc_email": (DC, "email"), "dc_contact": (DC, "mobile"),
                 "asm_email": (ASM, "email"), "asm_contact": (ASM, "mobile")}
FIELDS = ("ao", "rbo_name") + tuple(PEOPLE_FIELDS)


class CannotFix(Exception):
    """INFO cannot be changed safely for this suggestion; the reason is the
    message (shown to people)."""


def _block(rows: List[List[str]]) -> Tuple[int, Dict[str, int], List[int]]:
    """(header row index, {attribute: column}, [data row indexes]) of the
    AO block. Raises CannotFix when INFO has none."""
    for h, raw in enumerate(rows):
        cells = [str(c).strip() for c in (raw or [])]
        heads = [normalize(c) for c in cells]
        if heads and heads[0] == "lho" and "ao" in heads:
            columns = {}
            for i, head in enumerate(heads):
                attribute = AO_COLUMNS.get(head)
                if attribute and attribute not in columns:
                    columns[attribute] = i
                if head == "ao email id":
                    columns.setdefault("ao_email", i)
            data = []
            for r in range(h + 1, len(rows)):
                if not any(str(c).strip() for c in (rows[r] or [])):
                    break
                data.append(r)
            return h, columns, data
    raise CannotFix("INFO has no AO block")


def _cell(rows, r, c) -> str:
    row = rows[r] if r < len(rows) else []
    return str(row[c]).strip() if c is not None and c < len(row) else ""


def _rbo_of(rows, r, cols) -> str:
    code = _cell(rows, r, cols.get("rbo_code"))
    return f"RBO {code}" if code else " ".join(_cell(rows, r, cols.get("rbo_name")).split())


def _branches(text: str) -> List[str]:
    return [" ".join(b.split()) for b in (text or "").split(",") if b.strip()]


def plan(rows: List[List[str]], field: str, wrong: str, right: str,
         csps: List[dict]) -> List[dict]:
    """The changes that make INFO give `right` instead of `wrong` for these
    CSPs' branches. csps: [{"branch": , "state": , "district": }].

    Returns operations, in sheet terms (row = 1-based):
      {"op": "set", "row", "col", "before", "after"}
      {"op": "insert", "after_row", "values"}
    Raises CannotFix with the reason when it is not safe.
    """
    if field in PEOPLE_FIELDS:
        return _plan_person(rows, field, wrong, right)
    if field not in FIELDS:
        raise CannotFix(f"the app does not change {field} in INFO by itself")
    _, cols, data = _block(rows)
    if "branches" not in cols or "ao" not in cols:
        raise CannotFix("INFO's AO block has no Branch Name or AO column")

    def value(r):
        return (" ".join(_cell(rows, r, cols["ao"]).split()) if field == "ao"
                else _rbo_of(rows, r, cols))

    def in_state(r, state):
        return (not normalize(state) or "state" not in cols
                or normalize(_cell(rows, r, cols["state"])) == normalize(state))

    edits: Dict[int, List[str]] = {}       # row index -> its new branch list
    new_rows: Dict[tuple, dict] = {}       # (template row, district) -> row
    seen = set()
    for csp in csps:
        branch, state = (csp.get("branch") or "").strip(), csp.get("state") or ""
        if not branch:
            raise CannotFix("a corrected CSP has no Branch Name, so INFO cannot "
                            "be pointed at it")
        key = place_key(branch)
        if (key, normalize(state)) in seen:
            continue
        seen.add((key, normalize(state)))

        listed = [r for r in data if in_state(r, state) and key in
                  [place_key(b) for b in _branches(_cell(rows, r, cols["branches"]))]]
        if len(listed) > 1:
            raise CannotFix(f"branch {branch} is listed on {len(listed)} INFO rows "
                            f"in {state or 'the same State'} — a person must decide")
        if listed:
            source = listed[0]
        else:
            district = place_key(csp.get("district") or "")
            by_district = [r for r in data if in_state(r, state)
                           and place_key(_cell(rows, r, cols.get("district"))) == district
                           and normalize(value(r)) == normalize(wrong)]
            if not by_district:
                raise CannotFix(f"INFO no longer gives {wrong} for branch {branch} "
                                "— it may have been fixed already")
            source = by_district[0]
        if normalize(value(source)) != normalize(wrong):
            raise CannotFix(f"INFO no longer gives {wrong} for branch {branch} — "
                            "it may have been fixed already")

        if listed:
            current = edits.get(source, _branches(_cell(rows, source, cols["branches"])))
            edits[source] = [b for b in current if place_key(b) != key]

        district_key = place_key(_cell(rows, source, cols.get("district")))
        if field == "ao":
            want = (normalize(right), normalize(_rbo_of(rows, source, cols)))
        else:
            want = (normalize(_cell(rows, source, cols["ao"])), normalize(right))
        target = next((r for r in data if r != source and in_state(r, state)
                       and place_key(_cell(rows, r, cols.get("district"))) == district_key
                       and (normalize(_cell(rows, r, cols["ao"])),
                            normalize(_rbo_of(rows, r, cols))) == want), None)
        if target is not None:
            current = edits.get(target, _branches(_cell(rows, target, cols["branches"])))
            if key not in [place_key(b) for b in current]:
                edits[target] = current + [branch]
            continue

        # No row gives the right value there: a new one, copied from the old.
        slot = (source, district_key)
        if slot not in new_rows:
            width = max(len(rows[source]), max(cols.values()) + 1)
            values = [_cell(rows, source, i) for i in range(width)]
            if field == "ao":
                values[cols["ao"]] = right
                if "ao_email" in cols:
                    same = next((r for r in data if normalize(_cell(
                        rows, r, cols["ao"])) == normalize(right)), None)
                    values[cols["ao_email"]] = (_cell(rows, same, cols["ao_email"])
                                                if same is not None else "")
            else:
                number = right.split()[-1] if right.upper().startswith("RBO ") else ""
                if "rbo_code" in cols and number:
                    values[cols["rbo_code"]] = number
                elif "rbo_name" in cols:
                    values[cols["rbo_name"]] = right
            values[cols["branches"]] = ""
            # The District is left blank on a row the app adds: a district
            # with two different AOs (or RBOs) answers nothing for its
            # unlisted branches, so filling it would take their mapping
            # away. The branch is matched by name; the district keeps its
            # one value for everyone else.
            if "district" in cols:
                values[cols["district"]] = ""
            new_rows[slot] = {"after": source, "values": values, "branches": []}
        new_rows[slot]["branches"].append(branch)

    ops = []
    for r, branches in sorted(edits.items()):
        before = _cell(rows, r, cols["branches"])
        after = ", ".join(branches)
        if before != after:
            ops.append({"op": "set", "row": r + 1, "col": cols["branches"],
                        "before": before, "after": after})
    for slot, new in sorted(new_rows.items(), key=lambda kv: -kv[1]["after"]):
        values = list(new["values"])
        values[cols["branches"]] = ", ".join(new["branches"])
        ops.append({"op": "insert", "after_row": new["after"] + 1,
                    "values": values})
    if not ops:
        raise CannotFix("nothing to change — INFO already gives the right value")
    return ops


def _plan_person(rows: List[List[str]], field: str, wrong: str,
                 right: str) -> List[dict]:
    """The one cell of one person (a DC or an ASM) that holds `wrong`."""
    role, attribute = PEOPLE_FIELDS[field]
    hits, current, columns = [], None, {}
    for r, raw in enumerate(rows):
        cells = [str(c).strip() for c in (raw or [])]
        if not any(cells):
            current, columns = None, {}
            continue
        header = BLOCK_HEADERS.get(normalize(cells[0]))
        if header:
            current = header
            columns = {i: COLUMN_ALIASES.get(normalize(h))
                       for i, h in enumerate(cells[1:], start=1)}
            continue
        if current != role:
            continue
        col = next((i for i, a in columns.items() if a == attribute), None)
        if col is None:
            continue
        cell = cells[col] if col < len(cells) else ""
        if " ".join(cell.split()).lower() == " ".join(wrong.split()).lower():
            hits.append((r, col, cell))
    who = {DC: "DC", ASM: "ASM"}[role]
    if not hits:
        raise CannotFix(f"no {who} in INFO has {wrong} any more — it may have "
                        "been fixed already")
    if len(hits) > 1:
        raise CannotFix(f"{len(hits)} {who}s in INFO have {wrong} — a person "
                        "must decide whose it is")
    r, col, cell = hits[0]
    return [{"op": "set", "row": r + 1, "col": col, "before": cell,
             "after": right}]


def apply(spreadsheet_id: str, tab: str, ops: List[dict]) -> List[dict]:
    """Write the planned changes: cell edits first, then new rows from the
    bottom up (so no row number moves before it is used). Returns what was
    done, in words and cells, for the record."""
    from app.services import sheet_admin_service as sheets

    service = sheets._service()
    quoted = sheets._quote_tab(tab)
    done = []
    sets = [o for o in ops if o["op"] == "set"]
    if sets:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": [
                {"range": f"{quoted}!{sheets.column_letter(o['col'])}{o['row']}",
                 "values": [[o["after"]]]} for o in sets]}).execute()
        done += [{"cell": f"{sheets.column_letter(o['col'])}{o['row']}",
                  "before": o["before"], "after": o["after"]} for o in sets]
    inserts = sorted((o for o in ops if o["op"] == "insert"),
                     key=lambda o: -o["after_row"])
    if inserts:
        tab_id = sheets._tab_id(spreadsheet_id, tab)
        for o in inserts:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"insertDimension": {
                    "range": {"sheetId": tab_id, "dimension": "ROWS",
                              "startIndex": o["after_row"],
                              "endIndex": o["after_row"] + 1},
                    "inheritFromBefore": True}}]}).execute()
            row = o["after_row"] + 1
            # Where it ends up once the new rows above it are in too.
            final = row + sum(1 for x in inserts if x["after_row"] < o["after_row"])
            last = sheets.column_letter(len(o["values"]) - 1)
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{quoted}!A{row}:{last}{row}",
                valueInputOption="RAW",
                body={"values": [o["values"]]}).execute()
            done.append({"cell": f"row {final} (new)", "before": "",
                         "after": " | ".join(v for v in o["values"] if v)})
    logger.info("info_writer: %d change(s) written to %s", len(done), tab)
    return done
