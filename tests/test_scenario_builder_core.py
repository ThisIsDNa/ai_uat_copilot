"""Scenario builder assembly (schema alignment)."""

from src.scenario_builder_core import (
    apply_guided_snapshot_backfill,
    merge_legacy_story_into_scenario_context,
    normalize_loaded_scenario_dict,
    assign_ac_ids_for_bulk_rows,
    build_scenario_dict,
    format_tc_ac_link_lines,
    format_tc_ac_link_lines_for_export,
    hydrate_builder_session_from_scenario,
    normalize_ac_id_token,
    parse_acceptance_criteria_bulk_lines,
    parse_changed_areas_bulk,
    parse_steps_bulk,
    parse_test_case_title_and_steps_bulk,
    read_flat_builder_session,
    resolve_builder_scenario_id,
    suggest_scenario_id_from_title,
    tc_id_to_explicit_ac_ids,
    tc_title_text_and_steps_from_session,
    unmapped_test_case_ids,
)

from src.scenario_media import resolved_test_case_title


def test_apply_guided_snapshot_backfill_fills_blank_session():
    sess: dict = {"sb_story_title": "", "sb_workflow_name": "", "sb_wf_persisted_paths": []}
    snap = {
        "sb_story_title": "From snapshot",
        "sb_workflow_name": "WF",
        "sb_business_goal": "Goal",
        "sb_wf_persisted_paths": ["data/wf/a.png"],
        "sb_wf_lbl_0": "Main",
    }
    apply_guided_snapshot_backfill(sess, snap)
    assert sess["sb_story_title"] == "From snapshot"
    assert sess["sb_workflow_name"] == "WF"
    assert sess["sb_business_goal"] == "Goal"
    assert sess["sb_wf_persisted_paths"] == ["data/wf/a.png"]
    assert sess["sb_wf_lbl_0"] == "Main"


def test_apply_guided_snapshot_backfill_restores_wf_labels_when_widgets_unmounted():
    """Paths may already be persisted while caption keys were dropped (guided step 5 / save)."""
    sess: dict = {"sb_wf_persisted_paths": ["data/wf/a.png"]}
    snap = {"sb_wf_lbl_0": "After login"}
    apply_guided_snapshot_backfill(sess, snap)
    assert sess["sb_wf_lbl_0"] == "After login"


def test_merge_legacy_story_into_scenario_context_prefers_scenario_context():
    d = {
        "scenario_id": "x",
        "story_title": "S",
        "scenario_context": "From context",
        "story_description": "From story",
    }
    merge_legacy_story_into_scenario_context(d)
    assert d["scenario_context"] == "From context"


def test_merge_legacy_story_into_scenario_context_fills_empty():
    d = {
        "scenario_id": "x",
        "story_title": "S",
        "scenario_context": "",
        "story_description": "Legacy narrative.",
    }
    merge_legacy_story_into_scenario_context(d)
    assert d["scenario_context"] == "Legacy narrative."


def test_normalize_loaded_scenario_dict_migrates_workflow_and_tc_name():
    d = {
        "scenario_id": "x",
        "story_title": "S",
        "workflow_screenshots": ["data/wf.png"],
        "test_cases": [{"id": "TC-01", "name": "Named TC", "steps": ["a"]}],
    }
    normalize_loaded_scenario_dict(d)
    assert d["workflow_process_screenshots"] == ["data/wf.png"]
    assert d["test_cases"][0]["text"] == "Named TC"
    assert d["test_cases"][0]["title"] == "Named TC"


def test_resolved_test_case_title_prefers_title_field():
    assert resolved_test_case_title({"title": " A ", "text": "B"}) == "A"
    assert resolved_test_case_title({"text": " B "}) == "B"
    assert resolved_test_case_title({"name": " N "}) == "N"
    assert resolved_test_case_title({}) == ""


def test_parse_steps_bulk_numbered():
    assert parse_steps_bulk("1. First\n2. Second") == ["First", "Second"]
    assert parse_steps_bulk("- Bullet\n* Also") == ["Bullet", "Also"]


def test_normalize_ac_id_token():
    assert normalize_ac_id_token("AC-1") == "AC-01"
    assert normalize_ac_id_token("AC_12") == "AC-12"
    assert normalize_ac_id_token("AC99") == "AC-99"


def test_parse_acceptance_criteria_bulk_lines():
    text = "AC-01 First line\n* AC_02: Second\n\nThird without id\n4) AC-05 — Fifth style"
    rows = parse_acceptance_criteria_bulk_lines(text)
    assert rows[0] == ("AC-01", "First line")
    assert rows[1] == ("AC-02", "Second")
    assert rows[2] == (None, "Third without id")
    assert rows[3] == ("AC-05", "Fifth style")


def test_parse_test_case_title_and_steps_bulk():
    title, steps = parse_test_case_title_and_steps_bulk(
        "Title: Login flow\n1. Open app\n2. Sign in"
    )
    assert title == "Login flow"
    assert steps == ["Open app", "Sign in"]
    t2, s2 = parse_test_case_title_and_steps_bulk("1. Only\n2. Steps")
    assert t2 == ""
    assert s2 == ["Only", "Steps"]


def test_tc_title_widget_wins_over_paste_title_line():
    sess = {
        "sb_tc_0_text": "Widget TC title",
        "sb_tc_0_steps_bulk": "1. x",
        "sb_tc_0_title_steps_paste": "Title: From paste\n1. a\n2. b",
    }
    t, st = tc_title_text_and_steps_from_session(sess, 0)
    assert t == "Widget TC title"
    assert st == ["a", "b"]


def test_tc_title_text_from_paste_title_when_widget_empty():
    sess = {
        "sb_tc_0_text": "",
        "sb_tc_0_steps_bulk": "1. x",
        "sb_tc_0_title_steps_paste": "Title: From paste\n1. a\n2. b",
    }
    t, st = tc_title_text_and_steps_from_session(sess, 0)
    assert t == "From paste"
    assert st == ["a", "b"]


def test_assign_ac_ids_for_bulk_rows_fills_duplicates_and_missing():
    parsed = [("AC-01", "a"), ("AC-01", "b"), (None, "c")]
    out = assign_ac_ids_for_bulk_rows(parsed)
    assert out[0] == ("AC-01", "a")
    assert out[1][0] == "AC-02"
    assert out[1][1] == "b"
    assert out[2][0] == "AC-03"
    assert out[2][1] == "c"


def test_assign_ac_ids_for_bulk_rows_skips_empty_and_normalizes_ids():
    out = assign_ac_ids_for_bulk_rows(
        [
            ("AC-1", "first"),
            ("AC-01", "  "),
            ("AC_3", "third"),
            (None, "  fourth  "),
            ("bad-id", "fifth"),
        ]
    )
    # Order follows input; lowest-unused ids may not sort numerically when earlier slots stay free.
    assert out == [
        ("AC-01", "first"),
        ("AC-03", "third"),
        ("AC-02", "fourth"),
        ("AC-04", "fifth"),
    ]


def test_parse_changed_areas_bulk_colon():
    rows = parse_changed_areas_bulk("UI\nAPI: backend")
    assert rows[0] == {"area": "UI", "type": ""}
    assert rows[1] == {"area": "API", "type": "backend"}


def test_suggest_scenario_id_from_title():
    assert "login" in suggest_scenario_id_from_title("User Login Flow!")
    assert suggest_scenario_id_from_title("") == "built_scenario"


def test_build_scenario_dict_normalizes():
    d = build_scenario_dict(
        scenario_id="unit_test_builder",
        story_title="T",
        story_description="D",
        business_goal="G",
        workflow_name="W",
        workflow_process_screenshots=["data/x.png"],
        acceptance_criteria=[{"id": "AC-1", "text": "criterion", "test_case_ids": ["TC-01"]}],
        test_cases=[
            {
                "id": "TC-01",
                "text": "tc",
                "steps": ["a", "b"],
                "expected_step_screenshots": ["", "p/step.png"],
            }
        ],
        changed_areas=[{"area": "UI", "type": "frontend"}],
        known_dependencies=["API"],
        notes="n",
        scenario_context="Provider updates email.",
    )
    assert d["scenario_id"] == "unit_test_builder"
    assert d["scenario_title"] == "T"
    assert d["story_title"] == "T"
    assert isinstance(d["acceptance_criteria"], list)
    assert d["acceptance_criteria"][0]["test_case_ids"] == ["TC-01"]
    assert len(d["test_cases"][0]["steps"]) == 2
    assert d["known_dependencies"] == ["API"]
    assert d.get("scenario_context") == "Provider updates email."


def test_read_flat_includes_scenario_context():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "t",
        "sb_story_description": "",
        "sb_scenario_context": "Phone must be 10 digits.",
        "sb_workflow_name": "",
        "sb_business_goal": "",
        "sb_notes": "",
        "sb_n_ac": 0,
        "sb_n_tc": 0,
        "sb_n_ca": 0,
        "sb_n_dep": 0,
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    d = read_flat_builder_session(sess)
    assert d.get("scenario_context") == "Phone must be 10 digits."
    assert d.get("story_description") == ""


def test_read_flat_merges_extra_workflow_paths():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "wf",
        "sb_story_description": "",
        "sb_scenario_context": "",
        "sb_workflow_name": "",
        "sb_business_goal": "",
        "sb_notes": "",
        "sb_n_ac": 0,
        "sb_n_tc": 0,
        "sb_n_ca": 0,
        "sb_n_dep": 0,
    }
    d = read_flat_builder_session(sess, extra_workflow_paths=["data/json_upload_media/wf/b.png"])
    assert d["workflow_process_screenshots"] == ["data/json_upload_media/wf/b.png"]


def test_resolve_builder_scenario_id():
    assert resolve_builder_scenario_id({"sb_auto_id": True, "sb_story_title": "Hello World"}) == "hello_world"
    assert (
        resolve_builder_scenario_id(
            {
                "sb_auto_id": False,
                "sb_scenario_id": "",
                "sb_story_title": "  Named After Title  ",
            }
        )
        == "named_after_title"
    )


def test_read_flat_builder_session_minimal():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "My Flow",
        "sb_scenario_id": "",
        "sb_story_description": "desc",
        "sb_workflow_name": "wf",
        "sb_business_goal": "bg",
        "sb_notes": "",
        "sb_n_ac": 1,
        "sb_n_tc": 1,
        "sb_n_ca": 0,
        "sb_n_dep": 0,
        "sb_pick_ac_for_spawn": 0,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "One test",
        "sb_tc_0_n_steps": 1,
        "sb_tc_0_step_0_text": "Click go",
        "sb_ac_0_id": "AC-1",
        "sb_ac_0_text": "Must work",
        "sb_ac_0_map": ["TC-01"],
    }
    d = read_flat_builder_session(sess)
    assert d["scenario_id"] == "my_flow"
    assert d.get("story_description") == ""
    assert d.get("scenario_context") == "desc"
    assert d["acceptance_criteria"][0]["test_case_ids"] == ["TC-01"]
    assert d["test_cases"][0]["text"] == "One test"
    assert d["test_cases"][0]["title"] == "One test"


def test_tc_title_falls_back_to_session_when_paste_has_no_title_line():
    sess = {
        "sb_tc_0_text": "Widget title",
        "sb_tc_0_n_steps": 2,
        "sb_tc_0_step_0_text": "",
        "sb_tc_0_step_1_text": "",
        "sb_tc_0_title_steps_paste": "1. First\n2. Second",
    }
    title, steps = tc_title_text_and_steps_from_session(sess, 0)
    assert title == "Widget title"
    assert steps == ["First", "Second"]


def test_read_flat_uses_paste_when_structured_step_slots_empty():
    """Paste title/steps stay authoritative when per-step keys are empty (e.g. guided Final review)."""
    sess = {
        "sb_tc_0_text": "",
        "sb_tc_0_n_steps": 3,
        "sb_tc_0_step_0_text": "",
        "sb_tc_0_step_1_text": "",
        "sb_tc_0_step_2_text": "",
        "sb_tc_0_title_steps_paste": "Title: From Paste\n\n1. a\n2. b\n3. c",
    }
    title, steps = tc_title_text_and_steps_from_session(sess, 0)
    assert title == "From Paste"
    assert steps == ["a", "b", "c"]


def test_unmapped_test_case_ids():
    d = {
        "acceptance_criteria": [{"id": "AC-1", "text": "x", "test_case_ids": ["TC-01"]}],
        "test_cases": [
            {"id": "TC-01", "text": "a", "steps": [], "expected_step_screenshots": []},
            {"id": "TC-02", "text": "b", "steps": [], "expected_step_screenshots": []},
        ],
    }
    assert unmapped_test_case_ids(d) == ["TC-02"]


def test_read_flat_skips_inactive_test_case_rows():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "X",
        "sb_story_description": "",
        "sb_workflow_name": "",
        "sb_business_goal": "",
        "sb_notes": "",
        "sb_n_ac": 1,
        "sb_n_tc": 2,
        "sb_n_ca": 0,
        "sb_n_dep": 0,
        "sb_tc_0_active": False,
        "sb_tc_1_id": "TC-01",
        "sb_tc_1_text": "t",
        "sb_tc_1_n_steps": 0,
        "sb_ac_0_id": "AC-1",
        "sb_ac_0_text": "c",
        "sb_ac_0_map": ["TC-01"],
    }
    d = read_flat_builder_session(sess)
    assert len(d["test_cases"]) == 1
    assert d["test_cases"][0]["id"] == "TC-01"


def test_read_flat_merges_persisted_workflow_and_step_paths():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "Z",
        "sb_story_description": "",
        "sb_workflow_name": "",
        "sb_business_goal": "",
        "sb_notes": "",
        "sb_n_ac": 1,
        "sb_n_tc": 1,
        "sb_n_ca": 0,
        "sb_n_dep": 0,
        "sb_wf_persisted_paths": ["data/json_upload_media/z/wf_old.png"],
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "",
        "sb_tc_0_n_steps": 1,
        "sb_tc_0_step_0_text": "Go",
        "sb_tc_0_step_0_persisted_path": "data/json_upload_media/z/step_old.png",
        "sb_ac_0_id": "AC-1",
        "sb_ac_0_text": "c",
        "sb_ac_0_map": ["TC-01"],
    }
    d = read_flat_builder_session(
        sess,
        extra_workflow_paths=["data/json_upload_media/z/wf_new.png"],
        step_shot_overrides={(0, 0): "data/json_upload_media/z/step_new.png"},
    )
    assert d["workflow_process_screenshots"] == [
        "data/json_upload_media/z/wf_old.png",
        "data/json_upload_media/z/wf_new.png",
    ]
    assert d["test_cases"][0]["expected_step_screenshots"] == ["data/json_upload_media/z/step_new.png"]


def test_hydrate_merges_legacy_story_into_scenario_context():
    data = {
        "scenario_id": "legacy",
        "story_title": "T",
        "scenario_context": "",
        "story_description": "Only legacy narrative here.",
        "workflow_name": "",
        "business_goal": "",
        "notes": "",
        "workflow_process_screenshots": [],
        "changed_areas": [],
        "known_dependencies": [],
        "acceptance_criteria": [],
        "test_cases": [],
    }
    sess: dict = {}
    hydrate_builder_session_from_scenario(sess, data)
    assert sess.get("sb_scenario_context") == "Only legacy narrative here."


def test_hydrate_builder_session_sequential_tc_ids():
    data = {
        "scenario_id": "edit_demo",
        "story_title": "Demo",
        "story_description": "",
        "workflow_name": "",
        "business_goal": "",
        "notes": "",
        "workflow_process_screenshots": ["data/wf1.png"],
        "changed_areas": [],
        "known_dependencies": [],
        "acceptance_criteria": [
            {"id": "AC-1", "text": "Must", "test_case_ids": ["CUSTOM-A", "CUSTOM-B"]},
        ],
        "test_cases": [
            {"id": "CUSTOM-A", "text": "t1", "steps": ["s1"], "expected_step_screenshots": ["data/p1.png"]},
            {"id": "CUSTOM-B", "text": "t2", "steps": ["s2"], "expected_step_screenshots": [""]},
        ],
    }
    sess: dict = {}
    hydrate_builder_session_from_scenario(sess, data, editing_registry_id="edit_demo")
    out = read_flat_builder_session(sess)
    assert out["test_cases"][0]["id"] == "TC-01"
    assert out["test_cases"][1]["id"] == "TC-02"
    assert out["acceptance_criteria"][0]["test_case_ids"] == ["TC-01", "TC-02"]
    assert sess["sb_tc_0_step_0_persisted_path"] == "data/p1.png"


def test_format_tc_ac_link_lines_lists_all_acs_for_shared_tc():
    acs = [
        {"id": "AC-1", "text": "First", "test_case_ids": ["TC-01"]},
        {"id": "AC-2", "text": "Second", "test_case_ids": ["TC-01"]},
    ]
    lines = format_tc_ac_link_lines(acs, "TC-01")
    assert len(lines) == 2
    assert "AC-1" in lines[0] and "First" in lines[0]
    assert "AC-2" in lines[1] and "Second" in lines[1]
    assert tc_id_to_explicit_ac_ids(acs)["TC-01"] == ["AC-1", "AC-2"]


def test_format_tc_ac_link_lines_for_export_prefers_primary_slot():
    acs = [
        {"id": "AC-1", "text": "Precondition", "test_case_ids": ["TC-01"]},
        {"id": "AC-2", "text": "Draft editable", "test_case_ids": ["TC-01"]},
    ]
    all_lines = format_tc_ac_link_lines(acs, "TC-01")
    assert len(all_lines) == 2
    one = format_tc_ac_link_lines_for_export(acs, "TC-01", prefer_ac_slot_index=1)
    assert len(one) == 1
    assert "AC-2" in one[0] and "Draft editable" in one[0]
    assert format_tc_ac_link_lines_for_export(acs, "TC-01", prefer_ac_slot_index=99) == all_lines


def test_read_flat_changed_areas_from_slots_when_bulk_empty():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "T",
        "sb_story_description": "",
        "sb_workflow_name": "",
        "sb_business_goal": "",
        "sb_notes": "",
        "sb_n_ac": 1,
        "sb_n_tc": 1,
        "sb_n_ca": 1,
        "sb_n_dep": 0,
        "sb_changed_areas_bulk": "",
        "sb_ca_0_area": "Login modal",
        "sb_ca_0_type": "UI",
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "x",
        "sb_tc_0_n_steps": 1,
        "sb_tc_0_step_0_text": "s",
        "sb_ac_0_id": "AC-1",
        "sb_ac_0_text": "c",
        "sb_ac_0_map": ["TC-01"],
    }
    d = read_flat_builder_session(sess)
    assert d["changed_areas"] == [{"area": "Login modal", "type": "UI"}]


def test_read_flat_include_export_hints_sets_primary_ac_slot():
    sess = {
        "sb_auto_id": True,
        "sb_story_title": "T",
        "sb_story_description": "",
        "sb_workflow_name": "",
        "sb_business_goal": "",
        "sb_notes": "",
        "sb_n_ac": 2,
        "sb_n_tc": 1,
        "sb_n_ca": 0,
        "sb_n_dep": 0,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "Case",
        "sb_tc_0_n_steps": 1,
        "sb_tc_0_step_0_text": "go",
        "sb_tc_0_linked_ac": 1,
        "sb_ac_0_id": "AC-1",
        "sb_ac_0_text": "First",
        "sb_ac_0_map": ["TC-01"],
        "sb_ac_1_id": "AC-2",
        "sb_ac_1_text": "Second",
        "sb_ac_1_map": ["TC-01"],
    }
    d = read_flat_builder_session(sess, include_export_hints=True)
    assert d["test_cases"][0].get("_export_primary_ac_slot") == 1
    d2 = read_flat_builder_session(sess)
    assert "_export_primary_ac_slot" not in d2["test_cases"][0]


def test_build_scenario_dict_strips_export_only_tc_keys():
    raw = build_scenario_dict(
        scenario_id="x",
        story_title="T",
        story_description="",
        business_goal="",
        workflow_name="",
        workflow_process_screenshots=[],
        acceptance_criteria=[],
        test_cases=[{"id": "TC-01", "text": "a", "steps": ["s"], "_export_primary_ac_slot": 2}],
        changed_areas=[],
        known_dependencies=[],
        notes="",
    )
    assert "_export_primary_ac_slot" not in raw["test_cases"][0]


def test_tc_title_prefers_per_step_fields_over_paste():
    sess = {
        "sb_tc_0_text": "Saved title",
        "sb_tc_0_n_steps": 2,
        "sb_tc_0_step_0_text": "a",
        "sb_tc_0_step_1_text": "b",
        "sb_tc_0_title_steps_paste": "Title: X\n1. p\n2. q",
    }
    t, steps = tc_title_text_and_steps_from_session(sess, 0)
    assert t == "Saved title"
    assert steps == ["a", "b"]


def test_tc_title_uses_paste_when_steps_not_structured():
    sess = {
        "sb_tc_0_text": "",
        "sb_tc_0_n_steps": 1,
        "sb_tc_0_step_0_text": "",
        "sb_tc_0_title_steps_paste": "Title: Hi\n1. One\n2. Two",
    }
    t, steps = tc_title_text_and_steps_from_session(sess, 0)
    assert t == "Hi"
    assert steps == ["One", "Two"]
