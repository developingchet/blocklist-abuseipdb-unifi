"""Exercise the workflow's actual publication shell against a local Git remote."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
BASH = (str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt" else shutil.which("bash"))


@unittest.skipUnless(GIT and BASH and Path(BASH).is_file(), "Git and Bash are required")
class PublicationTests(unittest.TestCase):
    def test_initial_unchanged_updated_and_competing_writer(self):
        workflow = (ROOT / ".github/workflows/sync.yml").read_text()
        section = workflow.split("      - name: Publish all ten time windows on feeds branch\n", 1)[1]
        shell = textwrap.dedent(section.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Prevent user Git settings, line endings, signing, or hooks affecting the fixture.
            env = os.environ.copy()
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.test",
                       GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.test")
            def git(directory, *args):
                result = subprocess.run([GIT, "-c", "core.autocrlf=false", *args], cwd=directory,
                                        env=env, text=True, capture_output=True)
                if result.returncode:
                    self.fail(result.stderr)
                return result.stdout.strip()
            remote = root / "origin.git"
            git(root, "init", "--bare", "--initial-branch=main", str(remote))
            seed = root / "seed"
            git(root, "clone", str(remote), str(seed))
            (seed / "source.txt").write_text("source must not be published\n")
            git(seed, "add", ".")
            git(seed, "commit", "-m", "Source")
            git(seed, "push", "origin", "main")
            staging = root / "runner-temp"
            feeds = staging / "feeds"
            feeds.mkdir(parents=True)
            script = root / "publish.sh"
            script.write_text(shell, newline="\n")
            counter = 0
            def head():
                return git(remote, "rev-parse", "refs/heads/feeds")
            def publish(content, old_head="", success=True):
                nonlocal counter
                counter += 1
                repo = root / f"runner-{counter}"
                git(root, "clone", str(remote), str(repo))
                (feeds / "feed.txt").write_bytes(content)
                run_env = env | {"RUNNER_TEMP": staging.as_posix(), "FEEDS_OLD_HEAD": old_head}
                result = subprocess.run([BASH, str(script)], cwd=repo, env=run_env,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result
            publish(b"1.2.3.4\n")
            first = head()
            self.assertRegex(
                git(remote, "log", "-1", "--format=%s", "feeds"),
                r"^Sync AbuseIPDB feeds: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$",
            )
            self.assertEqual(git(remote, "ls-tree", "--name-only", "feeds"), "feed.txt")
            self.assertEqual(git(remote, "show", "feeds:feed.txt"), "1.2.3.4")
            result = publish(b"1.2.3.4\n", first)
            self.assertIn("Nothing to push", result.stdout)
            self.assertEqual(head(), first)
            publish(b"5.6.7.8\n", first)
            second = head()
            self.assertNotEqual(first, second)
            self.assertEqual(git(remote, "rev-list", "--count", "feeds"), "1")
            # A stale runner must not overwrite the newer snapshot.
            publish(b"9.10.11.12\n", first, success=False)
            self.assertEqual(head(), second)
            self.assertEqual(git(remote, "show", "feeds:feed.txt"), "5.6.7.8")
            # The empty lease also protects first publication against a competing creator.
            publish(b"13.14.15.16\n", success=False)
            self.assertEqual(head(), second)
