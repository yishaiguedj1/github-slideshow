# ממיר דיווחי ווצאפ ל-DAR

ממיר את הדיווחים של קבוצת הווצאפ (סריקות, בדיקות, ליווים) לשורות בתבנית ה-DAR המדויקת, בלי Claude API.
הודעות שהקוד לא מבין נאספות לקובץ, ומפוענחות בסשן של Claude Code (על חשבון המנוי) או ידנית.

## מבנה

```
dar/
  parse.py        ייצוא ווצאפ -> הודעות (זמן, שולח, טקסט; רב-שורתי, מערכת, נערך, נמחק)
  extract.py      שורת הודעה -> אירועים (סריקה / בדיקה / ליווי / מחסן / כותרת שעה)
  normalize.py    שמות עבריים -> שמות באנגלית, אזורים ומיקומים (C1/C2 + המיקומים ב-reference), קידומות וטעויות
  build.py        אירועים -> שורות DAR (זוגות, רציפות C2+C1, ליווים, Assumed Post, Shift)
  validate.py     כפילויות, שעות חריגות, ערכים לא ברשימה, חורים בדיווח
  write.py        כתיבה לתבנית (openpyxl, שומר עיצוב/רשימות/נוסחאות) + קובץ בדיקה נפרד
  evaluate.py     השוואה לאקסל אמיתי, שורה-שורה ושדה-שדה, דוח פערים
  corrections.py  תיקונים + למידה (כינויים חדשים, דוגמאות רגרסיה)
  pipeline.py     הרצה על טווח תאריכים (מקבל רשימת הודעות - מוכן לחיבור WAHA בהמשך)
config/settings.yaml          כללי הזנה (שעות יום, D/E, רציפות אזורים, ספים)
config/reference.example.yaml פורמט רשימת השמות (שמות בדויים)
config/event.schema.json      הסכמה הקשיחה של אירוע (לתיקונים)
```

הנתונים הפרטיים יושבים ב-`../data/` (ב-.gitignore): `whatsapp_chat.txt`, תבנית/אקסל אמיתי
`DAR_August_2026.xlsx`, `reference.yaml` (שמות), `corrections.yaml` (תיקונים), ופלטים ב-`out/`.

## הרצה

```bash
cd dar_converter
pip install -r requirements-dev.txt
python -m dar convert --from 2026-08-01 --to 2026-08-31      # DAR + קובץ בדיקה + pending.json
python -m dar evaluate --days 2026-08-16,2026-08-17,2026-08-19 --report ../data/out/eval.xlsx
python -m dar pending --from 2026-08-01 --to 2026-08-31      # שורות שלא זוהו, עם הקשר
python -m pytest -q
```

תבנית לכל חודש: הטווח חייב להיות בחודש של התבנית (`--template` לחודש אחר).

## כללים עיקריים (נלמדו מהימים שהוזנו ידנית)

- `39-42 X סרק Y בדק c2` -> Patrol של X + Material Search של Y (`Metal screening C2 : X - Declined to sit`).
- F = התחלה, G = סיום, D = F פחות דקה, E = F פחות 30 שניות. דקה בודדת ("44 בדיקה") -> 43-44.
- C2 ו-C1 של אותו סבב (פער עד 3 דק') נרשמים ברצף.
- ליווי: שורה לכל אדם ומיקום; מסתיים ב"סיום ליווי", בבדיקת היציאה באותו אזור, או בהחלפה.
- Assumed Post 07:00-19:00 לכל מאבטח שמופיע ביום; החלפה באמצע יום -> 07-13 / 13-19; ערב חג (`holidays`) -> עד 14:00.
- Shift לפי `shift_priority` ברשימת המאבטחים.
- סריקת מחסן, אזעקות ודיווחי מוקד - לא נכנסים.

## אין ניחושים

שדה לא ברור נשאר ריק עם סימון. שורה בביטחון נמוך לא נכתבת ל-DAR ומופיעה רק בקובץ הבדיקה
(`review_*.xlsx`) עם ההודעה המקורית. שורות שנכתבו עם סימון מקבלות הערה בתא (עמודה C).

## תיקונים ולמידה

`../data/corrections.yaml`:

```yaml
aliases:  {people: {"רוני": "Ron Shani"}, officers: {"דנוש": "Dana Cohen"}}
messages:
  "20260812-1846-a1b2c3": {text: "42-45 אבי סרק נועה בדקה c2"}   # טקסט מתוקן
  "20260809-1521-xxxxxx": {ignore: true}
  "20260819-1359-xxxxxx": {events: [{kind: check, start: "13:57", end: "13:58", zone: C1,
                                     actor: Noa Bar, subjects: [Tal Peretz]}]}
roster:   {"2026-08-23": [{name: Dana Cohen, slot: 1}, {name: Avi Levi, slot: 2}]}
holidays: ["2026-09-20"]
```

כל הרצה מחילה את הקובץ: כינויים חדשים נוספים ל-`reference.yaml`, והודעות מתוקנות נשמרות
ב-`examples.jsonl` ונבדקות בכל הרצת בדיקות. מזהה ההודעה מופיע בקובץ הבדיקה.
`pending_*.json` מיועד לסשן Claude: Claude כותב הצעות ל-`corrections.proposed.yaml`, ואתה מאשר.

## שלב 2 (לא נבנה עדיין)

`pipeline.run()` מקבל רשימת `Message`, כך ש-WAHA -> SQLite -> `Message` הוא מקור נוסף בלי שינוי בשאר.
כתיבה ישירה ל-Google Sheets (Sheets API) תחליף את `write.py` באותו ממשק.
