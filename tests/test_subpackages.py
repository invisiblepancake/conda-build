# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import re
import sys
from glob import glob
from pathlib import Path

import pytest
from conda.base.context import context

from conda_build import api, utils
from conda_build.exceptions import BuildScriptException, CondaBuildUserError
from conda_build.metadata import MetaDataTuple
from conda_build.render import finalize_metadata

from .utils import get_valid_recipes, subpackage_dir


@pytest.mark.slow
@pytest.mark.parametrize(
    "recipe",
    [
        pytest.param(recipe, id=recipe.name)
        for recipe in get_valid_recipes(subpackage_dir)
    ],
)
def test_subpackage_recipes(recipe: Path, testing_config):
    api.build(str(recipe), config=testing_config)


@pytest.mark.sanity
def test_autodetect_raises_on_invalid_extension(testing_config):
    with pytest.raises(NotImplementedError):
        api.build(
            os.path.join(subpackage_dir, "_invalid_script_extension"),
            config=testing_config,
        )


# regression test for https://github.com/conda/conda-build/issues/1661
def test_rm_rf_does_not_remove_relative_source_package_files(
    testing_config, monkeypatch
):
    recipe_dir = os.path.join(subpackage_dir, "_rm_rf_stays_within_prefix")
    monkeypatch.chdir(recipe_dir)
    bin_file_that_disappears = os.path.join("bin", "lsfm")
    if not os.path.isfile(bin_file_that_disappears):
        with open(bin_file_that_disappears, "w") as f:
            f.write("weee")
    assert os.path.isfile(bin_file_that_disappears)
    api.build("conda", config=testing_config)
    assert os.path.isfile(bin_file_that_disappears)


def test_output_pkg_path_shows_all_subpackages(testing_metadata):
    testing_metadata.meta["outputs"] = [{"name": "a"}, {"name": "b"}]
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    outputs = api.get_output_file_paths(
        [
            MetaDataTuple(metadata, False, False)
            for _, metadata in out_dicts_and_metadata
        ]
    )
    assert len(outputs) == 2


def test_subpackage_version_provided(testing_metadata):
    testing_metadata.meta["outputs"] = [{"name": "a", "version": "2.0"}]
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    outputs = api.get_output_file_paths(
        [
            MetaDataTuple(metadata, False, False)
            for _, metadata in out_dicts_and_metadata
        ]
    )
    assert len(outputs) == 1
    assert "a-2.0-1" in outputs[0]


def test_subpackage_independent_hash(testing_metadata):
    # this recipe is creating 2 outputs.  One is the output here, a.  The other is the top-level
    #     output, implicitly created by adding the run requirement.
    testing_metadata.meta["outputs"] = [{"name": "a", "requirements": "bzip2"}]
    testing_metadata.meta["requirements"]["run"] = ["a"]
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    assert len(out_dicts_and_metadata) == 2
    outputs = api.get_output_file_paths(
        [
            MetaDataTuple(metadata, False, False)
            for _, metadata in out_dicts_and_metadata
        ]
    )
    assert len(outputs) == 2
    assert outputs[0][-15:] != outputs[1][-15:]


def test_run_exports_in_subpackage(testing_metadata):
    p1 = testing_metadata.copy()
    p1.meta["outputs"] = [{"name": "has_run_exports", "run_exports": "bzip2 1.0"}]
    api.build(p1, config=testing_metadata.config)[0]
    p2 = testing_metadata.copy()
    p2.meta["requirements"]["host"] = ["has_run_exports"]
    p2_final = finalize_metadata(p2)
    assert "bzip2 1.0.*" in p2_final.meta["requirements"]["run"]


def test_subpackage_variant_override(testing_config):
    recipe = os.path.join(subpackage_dir, "_variant_override")
    outputs = api.build(recipe, config=testing_config)
    # Three total:
    #    one subpackage with no deps - one output
    #    one subpackage with a python dep, and 2 python versions - 2 outputs
    assert len(outputs) == 3


def test_intradependencies(testing_config):
    recipe = os.path.join(subpackage_dir, "_intradependencies")
    outputs1 = api.get_output_file_paths(recipe, config=testing_config)
    outputs1_set = {os.path.basename(p) for p in outputs1}
    # 2 * abc + 1 foo + 2 * (2 * abc, 1 * lib, 1 * foo)
    assert len(outputs1) == 11
    outputs2 = api.build(recipe, config=testing_config)
    assert len(outputs2) == 11
    outputs2_set = {os.path.basename(p) for p in outputs2}
    assert outputs1_set == outputs2_set, (
        f"pkgs differ :: get_output_file_paths()={outputs1_set} but build()={outputs2_set}"
    )


def test_git_in_output_version(testing_config, conda_build_test_recipe_envvar: str):
    recipe = os.path.join(subpackage_dir, "_git_in_output_version")
    metadata_tuples = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    assert len(metadata_tuples) == 1
    assert metadata_tuples[0][0].version() == "1.22.0"


def test_intradep_with_templated_output_name(testing_config):
    recipe = os.path.join(subpackage_dir, "_intradep_with_templated_output_name")
    metadata_tuples = api.render(recipe, config=testing_config)
    assert len(metadata_tuples) == 3
    expected_names = {
        "test_templated_subpackage_name",
        "templated_subpackage_nameabc",
        "depends_on_templated",
    }
    assert {metadata.name() for metadata, _, _ in metadata_tuples} == expected_names


def test_output_specific_subdir(testing_config):
    recipe = os.path.join(subpackage_dir, "_output_specific_subdir")
    metadata_tuples = api.render(recipe, config=testing_config)
    assert len(metadata_tuples) == 3
    for metadata, _, _ in metadata_tuples:
        if metadata.name() in ("default_subdir", "default_subdir_2"):
            assert metadata.config.target_subdir == context.subdir
        elif metadata.name() == "custom_subdir":
            assert metadata.config.target_subdir == "linux-aarch64"
        else:
            raise AssertionError(
                "Test for output_specific_subdir written incorrectly - "
                "package name not recognized"
            )


def test_about_metadata(testing_config):
    recipe = os.path.join(subpackage_dir, "_about_metadata")
    metadata_tuples = api.render(recipe, config=testing_config)
    assert len(metadata_tuples) == 2
    for metadata, _, _ in metadata_tuples:
        if metadata.name() == "abc":
            assert "summary" in metadata.meta["about"]
            assert metadata.meta["about"]["summary"] == "weee"
            assert "home" not in metadata.meta["about"]
        elif metadata.name() == "def":
            assert "home" in metadata.meta["about"]
            assert "summary" not in metadata.meta["about"]
            assert metadata.meta["about"]["home"] == "http://not.a.url"
    outs = api.build(recipe, config=testing_config)
    for out in outs:
        about_meta = utils.package_has_file(out, "info/about.json")
        assert about_meta
        info = json.loads(about_meta)
        if os.path.basename(out).startswith("abc"):
            assert "summary" in info
            assert info["summary"] == "weee"
            assert "home" not in info
        elif os.path.basename(out).startswith("def"):
            assert "home" in info
            assert "summary" not in info
            assert info["home"] == "http://not.a.url"


@pytest.mark.slow
def test_toplevel_entry_points_do_not_apply_to_subpackages(testing_config):
    recipe_dir = os.path.join(subpackage_dir, "_entry_points")
    outputs = api.build(recipe_dir, config=testing_config)
    if utils.on_win:
        script_dir = "Scripts"
        ext = ".exe"
    else:
        script_dir = "bin"
        ext = ""
    for out in outputs:
        fn = os.path.basename(out)
        if fn.startswith("split_package_entry_points1"):
            assert utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "pkg1", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "pkg2", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "top1", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "top2", ext)
            )
        elif fn.startswith("split_package_entry_points2"):
            assert utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "pkg2", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "pkg1", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "top1", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "top2", ext)
            )
        elif fn.startswith("test_split_package_entry_points"):
            # python commands will make sure that these are available.
            assert utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "top1", ext)
            )
            assert utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "top2", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "pkg1", ext)
            )
            assert not utils.package_has_file(
                out, "{}/{}{}".format(script_dir, "pkg2", ext)
            )
        else:
            raise ValueError(
                f"Didn't see any of the 3 expected filenames.  Filename was {fn}"
            )


def test_subpackage_hash_inputs(testing_config):
    recipe_dir = os.path.join(subpackage_dir, "_hash_inputs")
    outputs = api.build(recipe_dir, config=testing_config)
    assert len(outputs) == 2
    for out in outputs:
        if os.path.basename(out).startswith("test_subpackage"):
            assert utils.package_has_file(out, "info/recipe/install-script.sh")
            # will have full parent recipe in nested folder
            assert utils.package_has_file(out, "info/recipe/parent/build.sh")
            assert not utils.package_has_file(out, "info/recipe/meta.yaml.template")
            assert utils.package_has_file(out, "info/recipe/meta.yaml")
        else:
            assert utils.package_has_file(out, "info/recipe/install-script.sh")
            assert utils.package_has_file(out, "info/recipe/build.sh")
            # will have full parent recipe in base recipe folder (this is an output for the top level)
            assert utils.package_has_file(out, "info/recipe/meta.yaml.template")
            assert utils.package_has_file(out, "info/recipe/meta.yaml")


def test_overlapping_files(testing_config, caplog):
    recipe_dir = os.path.join(subpackage_dir, "_overlapping_files")
    utils.reset_deduplicator()
    outputs = api.build(recipe_dir, config=testing_config)
    assert len(outputs) == 3
    assert sum(int("Exact overlap" in rec.message) for rec in caplog.records) == 1


@pytest.mark.sanity
def test_per_output_tests(testing_config):
    recipe_dir = os.path.join(subpackage_dir, "_per_output_tests")
    api.build(recipe_dir, config=testing_config)
    # out, err = capfd.readouterr()
    # windows echoes commands, so we see the result and the command
    # count = 2 if utils.on_win else 1
    # assert out.count("output-level test") == count, out
    # assert out.count("top-level test") == count, out


@pytest.mark.sanity
def test_per_output_tests_script(testing_config):
    recipe_dir = os.path.join(subpackage_dir, "_output_test_script")
    with pytest.raises(CondaBuildUserError):
        api.build(recipe_dir, config=testing_config)


def test_pin_compatible_in_outputs(testing_config):
    recipe_dir = os.path.join(subpackage_dir, "_pin_compatible_in_output")
    metadata = api.render(recipe_dir, config=testing_config)[0][0]
    assert any(
        re.search(r"numpy\s*>=.*,<.*", req)
        for req in metadata.meta["requirements"]["run"]
    )


def test_output_same_name_as_top_level_does_correct_output_regex(testing_config):
    recipe_dir = os.path.join(subpackage_dir, "_output_named_same_as_top_level")
    metadata_tuples = api.render(recipe_dir, config=testing_config)
    # TODO: need to decide what best behavior is for saying whether the
    # top-level build reqs or the output reqs for the similarly naemd output
    # win. I think you could have both, but it means rendering a new, extra,
    # build-only metadata in addition to all the outputs
    for metadata, _, _ in metadata_tuples:
        if metadata.name() == "ipp":
            for env in ("build", "host", "run"):
                assert not metadata.meta.get("requirements", {}).get(env)


def test_subpackage_order_natural(testing_config):
    recipe = os.path.join(subpackage_dir, "_order")
    outputs = api.build(recipe, config=testing_config)
    assert len(outputs) == 2


def test_subpackage_order_bad(testing_config):
    recipe = os.path.join(subpackage_dir, "_order_bad")
    outputs = api.build(recipe, config=testing_config)
    assert len(outputs) == 2


@pytest.mark.sanity
def test_subpackage_script_and_files(testing_config):
    recipe = os.path.join(subpackage_dir, "_script_and_files")
    api.build(recipe, config=testing_config)


@pytest.mark.sanity
def test_build_script_and_script_env(testing_config):
    recipe = os.path.join(subpackage_dir, "_build_script")
    os.environ["TEST_FN"] = "test"
    api.build(recipe, config=testing_config)


@pytest.mark.sanity
def test_build_script_and_script_env_warn_empty_script_env(testing_config):
    recipe = os.path.join(subpackage_dir, "_build_script_missing_var")
    with pytest.warns(
        UserWarning,
        match="The environment variable 'TEST_FN_DOESNT_EXIST' specified in script_env is undefined",
    ):
        api.build(recipe, config=testing_config)


@pytest.mark.sanity
def test_build_script_does_not_set_env_from_script_env_if_missing(
    testing_config, capfd, monkeypatch
):
    monkeypatch.delenv("TEST_FN_DOESNT_EXIST", raising=False)
    recipe = os.path.join(subpackage_dir, "_build_script_relying_on_missing_var")
    with pytest.raises(BuildScriptException):
        api.build(recipe, config=testing_config)
    captured = capfd.readouterr()
    assert "KeyError: 'TEST_FN_DOESNT_EXIST'" in captured.err


@pytest.mark.sanity
@pytest.mark.skipif(sys.platform != "darwin", reason="only implemented for mac")
def test_strong_run_exports_from_build_applies_to_host(testing_config):
    recipe = os.path.join(
        subpackage_dir, "_strong_run_exports_applies_from_build_to_host"
    )
    api.build(recipe, config=testing_config)


@pytest.mark.parametrize(
    "recipe",
    (
        "_line_up_python_compiled_libs",
        "_line_up_python_compiled_libs_top_level_same_name_output",
    ),
)
def test_python_line_up_with_compiled_lib(recipe, testing_config):
    recipe = os.path.join(subpackage_dir, recipe)
    # we use windows so that we have 2 libxyz results (VS2008, VS2015)
    metadata_tuples = api.render(
        recipe, config=testing_config, platform="win", arch="64"
    )
    # 2 libxyz, 3 py-xyz, 3 xyz
    assert len(metadata_tuples) == 8
    for metadata, _, _ in metadata_tuples:
        if metadata.name() in ("py-xyz" or "xyz"):
            deps = metadata.meta["requirements"]["run"]
            assert any(
                dep.startswith("libxyz ") and len(dep.split()) == 3 for dep in deps
            ), (metadata.name(), deps)
            assert any(dep.startswith("python >") for dep in deps), (
                metadata.name(),
                deps,
            )
            assert any(dep.startswith("zlib >") for dep in deps), (
                metadata.name(),
                deps,
            )
        if metadata.name() == "xyz":
            deps = metadata.meta["requirements"]["run"]
            assert any(
                dep.startswith("py-xyz ") and len(dep.split()) == 3 for dep in deps
            ), (metadata.name(), deps)
            assert any(dep.startswith("python >") for dep in deps), (
                metadata.name(),
                deps,
            )


@pytest.mark.xfail(
    sys.platform == "win32", reason="Defaults channel has conflicting vc packages"
)
def test_merge_build_host_applies_in_outputs(testing_config):
    recipe = os.path.join(subpackage_dir, "_merge_build_host")
    metadata_tuples = api.render(recipe, config=testing_config)
    for metadata, _, _ in metadata_tuples:
        # top level
        if metadata.name() == "test_build_host_merge":
            assert not metadata.meta.get("requirements", {}).get("run")
        # output
        else:
            run_exports = set(metadata.meta.get("build", {}).get("run_exports", []))
            assert len(run_exports) == 2
            assert all(len(export.split()) > 1 for export in run_exports)
            run_deps = set(metadata.meta.get("requirements", {}).get("run", []))
            assert len(run_deps) == 2
            assert all(len(dep.split()) > 1 for dep in run_deps)

    api.build(recipe, config=testing_config)


@pytest.mark.sanity
def test_activation_in_output_scripts(testing_config):
    recipe = os.path.join(subpackage_dir, "_output_activation")
    testing_config.activate = True
    api.build(recipe, config=testing_config)


def test_inherit_build_number(testing_config):
    recipe = os.path.join(subpackage_dir, "_inherit_build_number")
    metadata_tuples = api.render(recipe, config=testing_config)
    for metadata, _, _ in metadata_tuples:
        assert "number" in metadata.meta["build"], (
            "build number was not inherited at all"
        )
        assert int(metadata.meta["build"]["number"]) == 1, (
            "build number should have been inherited as '1'"
        )


def test_circular_deps_cross(testing_config):
    recipe = os.path.join(subpackage_dir, "_circular_deps_cross")
    # check that this does not raise an exception
    api.render(recipe, config=testing_config)


@pytest.mark.slow
def test_loops_do_not_remove_earlier_packages(testing_config):
    recipe = os.path.join(subpackage_dir, "_xgboost_example")
    output_files = api.get_output_file_paths(recipe, config=testing_config)

    api.build(recipe, config=testing_config)
    assert len(output_files) == len(
        glob(os.path.join(testing_config.croot, testing_config.host_subdir, "*.conda"))
    )


# regression test for https://github.com/conda/conda-build/issues/3248
@pytest.mark.skipif(
    utils.on_win and sys.version_info <= (3, 4),
    reason="Skipping it on windows and vc<14",
)
def test_build_string_does_not_incorrectly_add_hash(testing_config):
    recipe = os.path.join(subpackage_dir, "_build_string_with_variant")
    output_files = api.get_output_file_paths(recipe, config=testing_config)
    assert len(output_files) == 4
    assert any("clang_variant-1.0-cling.conda" in f for f in output_files)
    assert any("clang_variant-1.0-default.conda" in f for f in output_files)


def test_multi_outputs_without_package_version(testing_config):
    # outputs without package/version is allowed
    recipe = os.path.join(subpackage_dir, "_multi_outputs_without_package_version")
    outputs = api.build(recipe, config=testing_config)
    assert len(outputs) == 3
    assert outputs[0].endswith("a-1-0.conda")
    assert outputs[1].endswith("b-2-0.conda")
    assert outputs[2].endswith("c-3-0.conda")


def test_empty_outputs_requires_package_version(testing_config):
    # no outputs means package/version is required
    recipe = os.path.join(subpackage_dir, "_empty_outputs_requires_package_version")
    with pytest.raises(SystemExit, match="package/version missing"):
        api.build(recipe, config=testing_config)
