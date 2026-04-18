"""Tests for scenario builder media helpers."""

from __future__ import annotations

import pytest

import src.scenario_builder_media as sbm


class _FakeUpload:
    def __init__(self, name: str, data: bytes = b"\x89PNG\r\n\x1a\n") -> None:
        self.name = name
        self._data = data

    def seek(self, *args: object) -> None:
        pass

    def read(self) -> bytes:
        return self._data


def test_persist_bulk_tc_step_screenshot_uploads_round_robin(tmp_path, monkeypatch) -> None:
    root = tmp_path / "json_upload_media"
    monkeypatch.setattr(sbm, "JSON_UPLOAD_MEDIA_ROOT", root)

    key = sbm.tc_bulk_step_upload_widget_key({"sb_upload_widget_epoch": 0}, 0)
    sess: dict = {
        "sb_upload_widget_epoch": 0,
        "sb_tc_0_active": True,
        key: [
            _FakeUpload("shot0.png"),
            _FakeUpload("shot1.jpg"),
            _FakeUpload("shot2.png"),
        ],
    }
    replaced = sbm.persist_bulk_tc_step_screenshot_uploads(
        sess, "my_scenario", n_tc=1, n_steps_for_tc=[3]
    )
    assert isinstance(replaced, bool)
    assert key not in sess
    p0 = sess.get("sb_tc_0_step_0_persisted_path")
    assert isinstance(p0, str) and "tc_01_step_01_bulk_01" in p0.replace("\\", "/")
    assert isinstance(sess.get("sb_tc_0_step_1_persisted_path"), str)
    assert isinstance(sess.get("sb_tc_0_step_2_persisted_path"), str)


def test_bulk_upload_file_indices_for_step_matches_persist_rule() -> None:
    # 4 files, 3 steps: indices 0,1,2 → steps 0,1,2; index 3 → step 0
    assert sbm.bulk_upload_file_indices_for_step(0, 3, 4) == [0, 3]
    assert sbm.bulk_upload_file_indices_for_step(1, 3, 4) == [1]
    assert sbm.bulk_upload_file_indices_for_step(2, 3, 4) == [2]
    assert sbm.bulk_upload_file_indices_for_step(0, 1, 2) == [0, 1]


def test_persist_bulk_appends_second_file_to_same_step_when_one_step(tmp_path, monkeypatch) -> None:
    root = tmp_path / "json_upload_media"
    monkeypatch.setattr(sbm, "JSON_UPLOAD_MEDIA_ROOT", root)

    key = sbm.tc_bulk_step_upload_widget_key({"sb_upload_widget_epoch": 0}, 0)
    sess: dict = {
        "sb_upload_widget_epoch": 0,
        "sb_tc_0_active": True,
        key: [_FakeUpload("a.png"), _FakeUpload("b.png")],
    }
    sbm.persist_bulk_tc_step_screenshot_uploads(sess, "z", n_tc=1, n_steps_for_tc=[1])
    plist = sess.get("sb_tc_0_step_0_persisted_paths")
    assert isinstance(plist, list) and len(plist) == 2
