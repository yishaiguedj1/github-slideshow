# CLAUDE.md - WhatsApp reports -> DAR (runbook for Claude sessions)

The user (a security-team supervisor) talks in Hebrew. Answer in Hebrew.
The converter lives in `dar_converter/` (see its README). It is deterministic (no Claude API);
lines it cannot read are resolved in the session with the user, never guessed.

## Privacy - this repository is PUBLIC

- Real names, the chat export, DAR files and the reference list live only in `data/`
  (git-ignored) and in the user's private Google Drive folder. Never commit them, never paste
  them into code, tests, comments or commit messages. Tests use the fictional names of
  `dar_converter/config/reference.example.yaml`.
- Before every commit, grep the diff for names from `data/reference.yaml` (Hebrew and English).

## Typical request (from the phone)

"תמלא את ה-DAR מ-<date> עד <date>" + a Drive link to the WhatsApp export (and maybe to the
month's official DAR). Goal: a Google Sheet in the user's Drive that looks exactly like the
daily sheet, with every row that needs a human marked red ("⚠ דרוש תיקון").

### 1. Private data -> `data/`

- Drive folder **"DAR converter - פרטי"** (search by title): `reference.yaml` (officers, people,
  aliases, senders, locations) and, if present, `corrections.yaml`. Save both to `data/`.
  If the folder is missing, ask the user - do not invent names.
- WhatsApp export: the link the user gives (a `.txt`, or a `.zip` with the `.txt` inside) ->
  `data/whatsapp_chat.txt`.
- Official DAR of the month: the link the user gives, or search Drive for
  `DAR <Month> <year>`; export as xlsx -> `data/DAR_<YYYY-MM>.xlsx`.
- Large Drive downloads come back as a saved tool-result file:
  `jq -r .content <file> | base64 -d > data/<name>`.

### 2. Convert

```bash
cd dar_converter && pip install -q -r requirements-dev.txt
python -m dar convert --from 2026-10-01 --to 2026-10-13 --template ../data/DAR_2026-10.xlsx
```

Outputs in `data/out/`: `DAR_<range>.xlsx` (the month file, filled), `review_<range>.xlsx`
(rows to check, with the original messages), `pending_<range>.json` (lines not understood).
One month per run (the template is a month file).

### 3. Unclear lines

Read `pending_*.json` and the red rows. Propose fixes in `data/corrections.proposed.yaml`
(format in the README), show them to the user in Hebrew, and only after approval move them to
`data/corrections.yaml` and run again. New names: ask for the English spelling as written in
the DAR and whether the person needs an escort (visitor / contractor) or not (employee).

### 4. Deliver as a Google Sheet

With the **Google Sheets** connector (preferred):
1. Copy the official month sheet with Drive `copy_file`
   (title: `DAR <month> <year> - מומר <from>-<to>`). Never write into the official sheet itself
   unless the user asks.
2. For every day tab in the range (tab names like `10/05`), read `A10:L400` with `get_values`
   and save `{"10/05": [[...], ...]}` to `data/out/existing.json` (camera-company rows -
   alarms, admin notes, Night Owl - are kept as they are).
3. `python -m dar sheets-plan --from ... --to ... --existing ../data/out/existing.json`
   -> write every `values` range of the plan with `update_values` (USER_ENTERED).
4. Sheet IDs from `get_spreadsheet` -> `{"10/05": 123, ...}` in `data/out/sheet_ids.json`;
   `python -m dar sheets-requests --plan <plan.json> --sheet-ids ../data/out/sheet_ids.json --out ../data/out/requests.json`
   -> apply with `update_spreadsheet` (red fill on rows to fix, notes on column C).
5. Give the user the link.

Without the connector: send the filled xlsx with SendUserFile (it opens in Google Sheets on
the phone) and suggest connecting "Google Sheets" at claude.ai -> Settings -> Connectors.

### 5. Report back (Hebrew, short)

Rows written per day, how many are red and why, open questions (new names, unclear lines).

### 6. Keep what was learned

If `reference.yaml` or `corrections.yaml` changed (`python -m dar learn`), upload the new
versions to the Drive folder "DAR converter - פרטי" (replace the old ones) so the next session
has them. The container is deleted when the session ends.

## Rules that came from the user (do not change without asking)

- Only scans, checks, escorts and Assumed Post rows. Alarms, admin notes and Night Owl rows
  belong to the camera company. Storage scans are never written; escorts in the office and
  the storage room are written like C1 / C2 ("Escort Office : ...", "Escort Storage : ...").
- Scan and check are separate rows. A check takes 1 minute; a contractor / visitor check with
  one reported time takes 2 minutes. A scan with one reported time takes 3 minutes.
- Shift 1 is the supervisor; posts come from the hours each officer reported (07-13 / 13-19 /
  full day); Shift 2 / Shift 3 follow the fixed order of `shift_priority`; holiday eves end
  at 14:00 (`config/settings.yaml` -> `day.holidays`). The first supervisor of the reference
  always has priority for Shift 1: when he appears in the chat the other supervisor is not
  Shift 1 (except the afternoon after he left at 13:00); when nobody supervisor-like reports,
  or the other supervisor scans like a guard, he is Shift 1 by default (cell note, not red).
- A round that reported only one zone gets the other zone added right after it, without a
  mark (3 minutes from the reported zone's end), unless another officer scanned that zone
  within 15 minutes. The review file lists every added row.
- The cleaner's escort with no exit report ends an hour after she came in, with a cell note
  (`default_minutes` in the reference). Her comment uses her name as written in the reference.
- Officers who left the team have a `left` date in the reference and are not matched after it.
- Unclear fields stay empty and the row is marked red. Minute-level precision is not critical;
  a clean, readable sheet is.
- Output: a separate copy of the month's official sheet in the user's Drive (never the
  official sheet itself unless asked).
- Days entered by the other supervisor are reference only, not the basis (they use other
  D/E offsets and comment wording).
