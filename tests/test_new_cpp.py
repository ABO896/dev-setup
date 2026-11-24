"""Regression tests for new-cpp and install.py (standard library only).

  python3 -m unittest discover -s tests -v

Tests that need cmake + ninja (and clang-tidy / clang-format) are skipped when those
tools aren't on PATH, so the fast checks run anywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NEW_CPP = REPO / "new-cpp"
INSTALL = REPO / "install.py"
EXE = ".exe" if sys.platform == "win32" else ""

HAVE_BUILD = bool(shutil.which("cmake") and shutil.which("ninja"))
HAVE_TIDY = bool(shutil.which("clang-tidy"))
HAVE_FORMAT = bool(shutil.which("clang-format"))


def run(args: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(NEW_CPP), *args], cwd=cwd,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


def run_patched(code: str, cwd: Path, env: dict[str, str] | None = None
                ) -> subprocess.CompletedProcess[str]:
    """Run a snippet in a fresh interpreter (used to fake the OS / symlink support)."""
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=cwd, env=env,
                          capture_output=True, text=True)


class TmpDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# --------------------------------------------------------------------------- generator

class TestGenerate(TmpDirTest):
    def test_cpp_project_files(self) -> None:
        r = run(["demo", "--no-git", "--no-configure"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        root = self.tmp / "demo"
        for f in ("CMakeLists.txt", "CMakePresets.json", ".clangd", ".clang-tidy",
                  ".clang-format", ".gitignore", ".zed/tasks.json", ".zed/debug.json",
                  ".zed/settings.json", "src/main.cpp"):
            self.assertTrue((root / f).is_file(), f)
        self.assertTrue((root / "include").is_dir())
        for f in ("CMakePresets.json", ".zed/tasks.json", ".zed/debug.json",
                  ".zed/settings.json"):
            json.loads((root / f).read_text(encoding="utf-8"))
        self.assertNotIn(b"\r\n", (root / "CMakeLists.txt").read_bytes())

    def test_output_survives_non_utf8_stdout(self) -> None:
        # Windows CI: piped stdout is cp1252, which can't encode the "→" in create()'s output.
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        r = run(["demo", "--no-git"], self.tmp, env=env, encoding="cp1252")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("UnicodeEncodeError", r.stderr)
        self.assertIn("demo", r.stdout)
        self.assertTrue((self.tmp / "demo/CMakeLists.txt").is_file())

    def test_cmake_globs_every_cpp_extension(self) -> None:
        run(["demo", "--no-git", "--no-configure"], self.tmp)
        cm = (self.tmp / "demo/CMakeLists.txt").read_text(encoding="utf-8")
        for ext in ("*.cpp", "*.cc", "*.cxx"):
            self.assertIn(f'/src/{ext}"', cm)

    def test_existing_cc_source_counts_as_cpp(self) -> None:
        (self.tmp / "src/sub").mkdir(parents=True)
        (self.tmp / "src/sub/app.cc").write_text("int main() { return 0; }\n")
        r = run(["proj", "--here", "--no-git", "--no-configure"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.tmp / "src/main.cpp").exists())

    def test_language_detected_from_c_sources(self) -> None:
        (self.tmp / "src").mkdir()
        (self.tmp / "src/a.c").write_text("int main(void) { return 0; }\n")
        r = run(["proj", "--here", "--no-git", "--no-configure"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("LANGUAGES C)", (self.tmp / "CMakeLists.txt").read_text())
        self.assertFalse((self.tmp / "src/main.c").exists())

    def test_explicit_language_mismatch_is_rejected(self) -> None:
        (self.tmp / "src").mkdir()
        (self.tmp / "src/a.cpp").write_text("int main() { return 0; }\n")
        r = run(["proj", "--here", "--lang", "c", "--no-git", "--no-configure"], self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--lang cpp", r.stderr)
        self.assertFalse((self.tmp / "CMakeLists.txt").exists())

    def test_invalid_names_are_rejected(self) -> None:
        cwd = self.tmp / "cwd"   # nested, so "../escaped" would land inside self.tmp
        cwd.mkdir()
        for name in ("my app", "../escaped", "1abc", "a/b", "-x"):
            with self.subTest(name=name):
                r = run(["--no-git", "--no-configure", "--", name], cwd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*")), ["cwd"])

    def test_here_sanitises_folder_name(self) -> None:
        d = self.tmp / "my app"
        d.mkdir()
        r = run(["--here", "--no-git", "--no-configure"], d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("project(my_app ", (d / "CMakeLists.txt").read_text())

    def test_here_rejects_unusable_folder_name(self) -> None:
        d = self.tmp / "1st"
        d.mkdir()
        self.assertEqual(run(["--here", "--no-git", "--no-configure"], d).returncode, 2)
        self.assertEqual(run(["ok", "--here", "--no-git", "--no-configure"], d).returncode, 0)

    def test_target_that_is_a_file_is_rejected(self) -> None:
        (self.tmp / "demo").write_text("not a folder")
        self.assertEqual(run(["demo", "--no-git", "--no-configure"], self.tmp).returncode, 2)

    def test_std_validation(self) -> None:
        cases = [("cpp", "26", 0), ("cpp", "17", 0), ("cpp", "11", 2), ("cpp", "99", 2),
                 ("c", "99", 0), ("c", "23", 0), ("c", "20", 2)]
        for i, (lang, std, code) in enumerate(cases):
            with self.subTest(lang=lang, std=std):
                r = run([f"p{i}", "--lang", lang, "--std", std, "--no-git", "--no-configure"],
                        self.tmp)
                self.assertEqual(r.returncode, code, r.stderr)

    def test_never_overwrites(self) -> None:
        run(["demo", "--no-git", "--no-configure"], self.tmp)
        main = self.tmp / "demo/src/main.cpp"
        main.write_text("// mine\nint main() { return 0; }\n")
        r = run(["--here", "--no-git", "--no-configure"], self.tmp / "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(main.read_text(), "// mine\nint main() { return 0; }\n")

    def test_header_filter_matches_both_separators(self) -> None:
        import re
        run(["demo", "--no-git", "--no-configure"], self.tmp)
        line = next(l for l in (self.tmp / "demo/.clang-tidy").read_text().splitlines()
                    if l.startswith("HeaderFilterRegex:"))
        rx = re.compile(line.split(":", 1)[1].strip().strip("'"))
        self.assertTrue(rx.fullmatch("/home/u/p/include/x.h"))
        self.assertTrue(rx.fullmatch("C:\\u\\p\\include\\x.h"))
        self.assertTrue(rx.fullmatch("C:/u/p/include\\x.h"))
        self.assertFalse(rx.fullmatch("/home/u/p/build/gen.h"))

    def test_windows_output(self) -> None:
        r = run_patched(f"""
            import platform, runpy, sys
            platform.system = lambda: "Windows"
            sys.argv = ["new-cpp", "demo", "--no-git", "--no-configure"]
            runpy.run_path({str(NEW_CPP)!r}, run_name="__main__")
        """, self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        root = self.tmp / "demo"
        tasks = json.loads((root / ".zed/tasks.json").read_text())
        self.assertTrue(all(t["shell"] == {"program": "pwsh"} for t in tasks))
        self.assertIn("./build/debug/demo.exe", json.dumps(tasks))
        dbg = json.loads((root / ".zed/debug.json").read_text())
        self.assertTrue(dbg[0]["program"].endswith("/build/debug/demo.exe"))
        cache = json.loads((root / "CMakePresets.json").read_text())["configurePresets"][0]
        self.assertEqual(cache["cacheVariables"]["CMAKE_CXX_COMPILER"], "clang++")
        self.assertIn("if(MINGW)", (root / "CMakeLists.txt").read_text())

    @unittest.skipUnless(HAVE_FORMAT, "clang-format not on PATH")
    def test_templates_match_project_style(self) -> None:
        for lang, main in (("cpp", "src/main.cpp"), ("c", "src/main.c")):
            with self.subTest(lang=lang):
                run([f"p_{lang}", "--lang", lang, "--no-git", "--no-configure"], self.tmp)
                r = subprocess.run(["clang-format", "--dry-run", "--Werror", main],
                                   cwd=self.tmp / f"p_{lang}", capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(HAVE_BUILD, "cmake/ninja not on PATH")
class TestToolchain(TmpDirTest):
    def cmake(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["cmake", *args], cwd=root, capture_output=True, text=True)

    def test_configure_failure_gives_nonzero_exit(self) -> None:
        (self.tmp / "CMakeLists.txt").write_text("this is not cmake(\n")
        r = run(["proj", "--here", "--no-git"], self.tmp)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("cmake configure failed", r.stdout)

    def check_project(self, lang: str) -> None:
        r = run(["demo", "--lang", lang, "--no-git"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        root = self.tmp / "demo"
        t = self.cmake(root, "--workflow", "--preset", "test")
        self.assertEqual(t.returncode, 0, t.stdout + t.stderr)
        out = subprocess.run([str(root / "build/debug" / f"demo{EXE}")],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "sum = 15")
        if HAVE_TIDY:
            lint = self.cmake(root, "--workflow", "--preset", "lint")
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
            self.assertNotIn("warning:", lint.stdout + lint.stderr)

    def test_cpp_workflow_and_clean_lint(self) -> None:
        self.check_project("cpp")

    def test_c_workflow_and_clean_lint(self) -> None:
        self.check_project("c")

    def test_cc_sources_build(self) -> None:
        (self.tmp / "src").mkdir()
        (self.tmp / "src/app.cc").write_text("int main() { return 0; }\n")
        r = run(["proj", "--here", "--no-git"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = self.cmake(self.tmp, "--workflow", "--preset", "debug")
        self.assertEqual(b.returncode, 0, b.stdout + b.stderr)


# --------------------------------------------------------------------------- install.py

class TestInstall(TmpDirTest):
    def install(self, system: str = "", no_symlinks: bool = False, xdg: str = ""
                ) -> subprocess.CompletedProcess[str]:
        """Run install.py with a temp HOME; `system` fakes platform.system() if given."""
        home = self.tmp / "home"
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                   APPDATA=str(self.tmp / "appdata"))
        env.pop("XDG_CONFIG_HOME", None)
        if xdg:
            env["XDG_CONFIG_HOME"] = xdg
        return run_patched(f"""
            import pathlib, platform, runpy, sys
            if {no_symlinks}:
                def nosym(self, *a, **k): raise OSError("no symlink privilege")
                pathlib.Path.symlink_to = nosym
            if {system!r}:
                platform.system = lambda: {system!r}
            sys.argv = ["install.py"]
            runpy.run_path({str(INSTALL)!r}, run_name="__main__")
        """, self.tmp, env)

    def bin_dir(self) -> list[str]:
        return sorted(p.name for p in (self.tmp / "home/.local/bin").iterdir())

    def test_copy_fallback_is_idempotent(self) -> None:
        for _ in range(3):
            r = self.install(system="Windows", no_symlinks=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bin_dir(), ["new-cpp"])

    def test_stale_copy_is_backed_up_once(self) -> None:
        self.install(system="Windows", no_symlinks=True)
        (self.tmp / "home/.local/bin/new-cpp").write_text("old version")
        self.install(system="Windows", no_symlinks=True)
        self.install(system="Windows", no_symlinks=True)
        names = self.bin_dir()
        self.assertEqual(len(names), 2, names)
        self.assertTrue(names[1].startswith("new-cpp.bak-"))

    def test_windows_tasks_rendered(self) -> None:
        self.install(system="Windows", no_symlinks=True)
        text = (self.tmp / "appdata/Zed/tasks.json").read_text(encoding="utf-8")
        self.assertNotIn("__HOME__", text)
        home = (self.tmp / "home").as_posix()
        self.assertIn(f'"{home}/.local/bin/new-cpp"', text)
        self.assertIn(f'"cwd": "{home}"', text)
        r = self.install(system="Windows", no_symlinks=True)
        self.assertIn("up to date", r.stdout)

    @unittest.skipIf(sys.platform == "win32", "symlinks need Developer Mode on Windows")
    def test_unix_symlinks_idempotent(self) -> None:
        for _ in range(2):
            r = self.install()
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already linked", r.stdout)
        self.assertEqual(self.bin_dir(), ["new-cpp"])
        self.assertTrue((self.tmp / "home/.config/zed/tasks.json").is_symlink())


    @unittest.skipIf(sys.platform == "win32", "symlinks need Developer Mode on Windows")
    def test_linux_links_linux_tasks(self) -> None:
        r = self.install(system="Linux")
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = self.tmp / "home/.config/zed/tasks.json"
        self.assertEqual(dest.resolve(), (REPO / "zed/tasks.linux.json").resolve())

    @unittest.skipIf(sys.platform == "win32", "symlinks need Developer Mode on Windows")
    def test_linux_honours_xdg_config_home(self) -> None:
        xdg = self.tmp / "xdg"
        r = self.install(system="Linux", xdg=str(xdg))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((xdg / "zed/tasks.json").is_symlink())
        self.assertFalse((self.tmp / "home/.config/zed").exists())
        # A relative XDG_CONFIG_HOME is invalid per the XDG spec and must be ignored.
        r = self.install(system="Linux", xdg="relative/dir")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "home/.config/zed/tasks.json").is_symlink())

    def test_global_task_files_are_valid(self) -> None:
        # Zed's tasks.json allows // comments; strip them and parse the rest as JSON.
        for name in ("tasks.mac.json", "tasks.linux.json", "tasks.windows.json"):
            text = (REPO / "zed" / name).read_text(encoding="utf-8")
            body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
            labels = [t["label"] for t in json.loads(body)]
            self.assertIn("C/C++: new project (wizard)", labels, name)


if __name__ == "__main__":
    unittest.main()
