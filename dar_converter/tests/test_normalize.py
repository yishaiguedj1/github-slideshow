from dar.normalize import Reference


def test_prefixes_and_kinds(ref):
    assert ref.lookup("לרון").name == "Ron Shani"
    assert ref.lookup("ורון").kind == "person"
    assert ref.lookup("לדנה").name == "Dana Cohen" and ref.lookup("לדנה").kind == "officer"
    assert ref.lookup("המנקה").name == "Mira Katz"


def test_fuzzy_typo_lowers_confidence(ref):
    m = ref.lookup("נועע")              # one-letter typo of נועה
    assert m.name == "Noa Bar" and m.confidence < 1
    assert ref.lookup("שלמה") is None   # unknown names are not guessed


def test_locations(ref):
    assert ref.location("с1") == "C1"           # Cyrillic es
    assert ref.location("V2") == "C2"
    assert ref.location("במחסן") == "Storage"
    assert ref.location("מהמשרס") == "Office"   # typo
    assert ref.location("bldg 7") == "BLDG7"
    assert ref.location("חיים") is None


def test_sender_mapping(ref):
    assert ref.sender_officer("נועה - עבודה - חברה") == "Noa Bar"
    assert ref.sender_officer("מישהו אחר") is None


def test_add_alias_and_roundtrip(tmp_path, ref):
    r = Reference.from_dict(ref.to_dict())
    assert r.add_alias("רוני", "Ron Shani", "person")
    assert not r.add_alias("רוני", "Ron Shani", "person")
    r.save(tmp_path / "ref.yaml")
    again = Reference.load(tmp_path / "ref.yaml")
    assert again.lookup("לרוני").name == "Ron Shani"
