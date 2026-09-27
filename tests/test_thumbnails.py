import json
import sqlite3

import pytest

from eln import thumbnails as th


# ---- ranking (pure, no image libraries needed) ------------------------------

def _score(path):
    return th.classify(path)[0]


def test_processed_results_outrank_raw():
    raw = "/x/VIMFM-01/raw/NLS.ome.zarr"
    assert _score("/x/VIMFM-01/processed/TFM_data/pos01/figures/force_cell_overlay.mp4") > _score(raw)
    assert _score("/x/COV2D-01/processed/pos00/cell_labels.tif") > _score(raw)
    assert _score("/x/OPTOV-01/processed/frame_04.png") > _score(raw)
    assert _score("/x/FFDVI-01/processed/crops/crop00.tif") > _score(raw)


def test_processed_tiers_are_ordered():
    fco = _score("/x/A/processed/p/figures/force_cell_overlay.mp4")
    labels = _score("/x/A/processed/p/cell_labels.tif")
    nuc = _score("/x/A/processed/p/nucleus_labels.tif")
    fmap = _score("/x/A/processed/p/figures/force_map.gif")
    movie = _score("/x/A/processed/A_pos00_cherry-trans.mp4")
    assert fco > labels > nuc > fmap > movie


def test_masks_and_qc_fall_below_raw():
    raw = "/x/A/raw/nuclei_stack.tif"
    assert _score("/x/A/processed/mask01.tif") < _score(raw)
    assert _score("/x/A/processed/pos00/masks.tif") < _score(raw)
    assert _score("/x/A/processed/nls_qc/nls_overview_pos02.png") < _score(raw)
    assert _score("/x/A/processed/tfm/registration_diagnostic.png") < _score(raw)
    assert _score("/x/A/processed/tfm/reference_registered_overlay.png") < _score(raw)


def test_plain_stacks_under_processed_follow_raw_channel_rules():
    beads = "/x/A/processed/Ctrl/pos_00/beads.tif"
    cells = "/x/A/processed/Ctrl/pos_00/cells.tif"
    assert _score(cells) > _score(beads)
    assert _score(cells) > _score("/x/A/raw/beads.tif")


def test_archives_and_inputs_are_skipped():
    assert th.classify("/x/A/processed/KO/archive/pos_03/masks.tif")[1] == "skipped"
    assert th.classify("/x/A/processed/TFM_inputs_z_registered/pos00/cells.tif")[1] == "skipped"
    assert th.classify("/x/A/raw/TFM.ome.zarr")[1] == "raw"


def test_rank_key_prefers_first_position_then_local_copy():
    a = ("helix", "/h/A/processed/pos07/cell_labels.tif", 10)
    b = ("helix", "/h/A/processed/pos00/cell_labels.tif", 10)
    c = ("data", "/d/A/processed/pos03/cell_labels.tif", 10)
    assert sorted([a, b, c], key=th.rank_key) == [c, b, a]


def test_raw_ties_break_on_size():
    small = ("helix", "/h/A/raw/nls_a.tif", 10)
    big = ("helix", "/h/A/raw/nls_b.tif", 10_000)
    assert sorted([small, big], key=th.rank_key)[0] == big


# ---- discovery --------------------------------------------------------------

def test_walk_dataset_finds_direct_and_nested_folders(tmp_path):
    (tmp_path / "A" / "COV2D-01" / "raw").mkdir(parents=True)
    (tmp_path / "A" / "COV2D-01" / "raw" / "s.tif").write_bytes(b"x")
    (tmp_path / "B" / "sub" / "COV2D-01" / "store.zarr" / "0").mkdir(parents=True)
    (tmp_path / "B" / "sub" / "COV2D-01" / "store.zarr" / "0" / "chunk.png").write_bytes(b"x")
    (tmp_path / "B" / "sub" / "COV2D-01" / "notes.txt").write_text("no")
    roots = [{"name": "a", "path": tmp_path / "A"}, {"name": "b", "path": tmp_path / "B"},
             {"name": "gone", "path": tmp_path / "missing"}]
    found = th.walk_dataset("COV2D-01", roots)
    paths = sorted(p for _, p, _ in found)
    assert paths == [str(tmp_path / "A/COV2D-01/raw/s.tif"),
                     str(tmp_path / "B/sub/COV2D-01/store.zarr")]


def _db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE experiment_codes (title TEXT, code TEXT);
        CREATE TABLE experiments (id INTEGER PRIMARY KEY, experiment_type TEXT,
            repetition INTEGER, excluded INTEGER, thumbnail_path TEXT);
        INSERT INTO experiment_codes VALUES ('Co-cultures', 'COV2D');
        INSERT INTO experiments VALUES (7, 'Co-cultures', 3, 0, NULL);
        INSERT INTO experiments VALUES (8, 'Co-cultures', 1, 1, 'thumbnails/old.png');
        INSERT INTO experiments VALUES (9, 'Unknown series', 1, 0, NULL);
    """)
    conn.commit()
    conn.close()


def test_dataset_keys_builds_code_nn_from_titles(tmp_path):
    _db(tmp_path / "experiments.db")
    assert th.dataset_keys(tmp_path / "experiments.db") == {"COV2D-03": 7, "COV2D-X01": 8}


def test_generate_rejects_bad_keys(tmp_path):
    with pytest.raises(ValueError):
        th.generate(tmp_path, [], keys=["cov2d-1"])


def test_generate_dry_run_reports_choice_and_writes_nothing(tmp_path, capsys):
    _db(tmp_path / "experiments.db")
    root = tmp_path / "data"
    (root / "COV2D-03" / "processed" / "pos00").mkdir(parents=True)
    (root / "COV2D-03" / "processed" / "pos00" / "cell_labels.tif").write_bytes(b"x")
    (root / "COV2D-03" / "raw").mkdir()
    (root / "COV2D-03" / "raw" / "nls.tif").write_bytes(b"x" * 100)
    lines = []
    res = th.generate(tmp_path, [{"name": "data", "path": root}], dry_run=True,
                      report=lines.append)
    assert res["COV2D-03"]["kind"] == "cell labels"
    assert res["COV2D-X01"] is None
    assert not (tmp_path / "thumbnails").exists()
    assert any(l.startswith("pick COV2D-03") for l in lines)
    assert any(l.startswith("none COV2D-X01") for l in lines)


# ---- rendering (needs the optional image stack) -----------------------------

def test_generate_renders_labels_and_links_empty_thumbnail_paths(tmp_path):
    np = pytest.importorskip("numpy")
    tifffile = pytest.importorskip("tifffile")
    pytest.importorskip("PIL")
    _db(tmp_path / "experiments.db")
    root = tmp_path / "data"
    pos = root / "COV2D-03" / "processed" / "pos00"
    pos.mkdir(parents=True)
    lab = np.zeros((3, 64, 64), np.int32)
    lab[1, 10:30, 10:30] = 1
    lab[1, 40:60, 40:60] = 2
    tifffile.imwrite(pos / "cell_labels.tif", lab)
    (root / "COV2D-X01" / "raw").mkdir(parents=True)
    tifffile.imwrite(root / "COV2D-X01" / "raw" / "nls.tif",
                     (np.random.default_rng(0).random((2, 32, 32)) * 4000).astype(np.uint16))

    res = th.generate(tmp_path, [{"name": "data", "path": root}], report=lambda s: None)
    assert res["COV2D-03"]["kind"] == "cell labels"
    assert res["COV2D-X01"]["kind"] == "raw"
    assert (tmp_path / "thumbnails" / "COV2D-03.png").exists()
    sources = json.loads((tmp_path / "thumbnails" / "sources.json").read_text())
    assert sources["COV2D-03"]["path"].endswith("cell_labels.tif")

    from PIL import Image
    img = Image.open(tmp_path / "thumbnails" / "COV2D-03.png").convert("RGB")
    px = np.asarray(img)
    assert img.size == (64, 64)
    assert tuple(px[0, 0]) == (0, 0, 0)                       # background stays black
    assert tuple(px[20, 20]) != (0, 0, 0)                     # label 1 coloured
    assert tuple(px[20, 20]) != tuple(px[50, 50])             # labels differ

    conn = sqlite3.connect(str(tmp_path / "experiments.db"))
    rows = dict(conn.execute("SELECT id, thumbnail_path FROM experiments"))
    conn.close()
    assert rows[7] == "thumbnails/COV2D-03.png"
    assert rows[8] == "thumbnails/old.png"                    # existing value untouched

    # A second run keeps the rendered files unless forced.
    lines = []
    th.generate(tmp_path, [{"name": "data", "path": root}], report=lines.append)
    assert all(l.startswith("keep") for l in lines)


def test_trim_border_removes_uniform_margin():
    pytest.importorskip("PIL")
    from PIL import Image
    img = Image.new("RGB", (100, 80), "white")
    for x in range(30, 70):
        for y in range(20, 60):
            img.putpixel((x, y), (200, 0, 0))
    assert th.trim_border(img).size == (40, 40)
    assert th.trim_border(Image.new("RGB", (50, 50), "white")).size == (50, 50)


def test_crop_figure_panel_drops_a_colourbar_strip_but_not_sparse_content():
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (100, 130), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 99, 99), fill=(120, 120, 120))       # the data panel
    d.rectangle((10, 112, 89, 120), fill=(200, 80, 0))       # colourbar below a gap
    assert th.crop_figure_panel(img).size == (100, 100)

    sparse = Image.new("RGB", (100, 100), "white")
    d = ImageDraw.Draw(sparse)
    d.ellipse((5, 5, 30, 30), fill=(0, 0, 200))
    d.ellipse((60, 60, 95, 95), fill=(0, 0, 200))            # white rows in between
    assert th.crop_figure_panel(sparse).size == (100, 100)


def test_first_panel_keeps_left_square_of_a_montage():
    pytest.importorskip("PIL")
    from PIL import Image
    assert th.first_panel(Image.new("RGB", (200, 100))).size == (100, 100)
    assert th.first_panel(Image.new("RGB", (150, 100))).size == (150, 100)
