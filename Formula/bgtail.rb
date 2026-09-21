class Bgtail < Formula
  include Language::Python::Virtualenv

  desc "Run long-running commands detached with minimal heartbeat"
  homepage "https://github.com/PeachlifeAB/bgtail"
  url "https://github.com/PeachlifeAB/homebrew-tap/releases/download/bgtail-0.1.2/bgtail-0.1.2.tar.gz"
  sha256 "6bff80753ebd5c6454af4b79aa665bd27c9873bf2601011aa392a35d9345295d"
  license "MIT"

  livecheck do
    url :stable
    strategy :github_releases
    regex(/^bgtail-v?(\d+(?:\.\d+)+)$/i)
  end

  depends_on "python@3.13"

  # Build backend. Homebrew's python vendors only pip, and the build sandbox has
  # no network, so an isolated build cannot fetch it. Vendored here and installed
  # into the venv, which `build_isolation: false` below then builds against.
  resource "setuptools" do
    url "https://files.pythonhosted.org/packages/34/26/f5d29e25ffdb535afef2d35cdb55b325298f96debd670da4c325e08d70f4/setuptools-83.0.0.tar.gz"
    sha256 "025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef"
  end

  def install
    venv = virtualenv_create(libexec, "python3.13")
    venv.pip_install resources
    venv.pip_install_and_link buildpath, build_isolation: false
  end

  test do
    assert_equal "bgtail #{version}", shell_output("#{bin}/bgtail --version").strip

    # bgtail's whole job is detaching a child and streaming it to a log, so the
    # only proof it works is running one. `--project-log` writes under the
    # working directory, which keeps this inside testpath.
    require "timeout"

    marker = "brew-runtime-proof"
    pid = spawn bin/"bgtail", "--project-log", "--no-log-popup", "echo", marker,
                out: (testpath/"bgtail.out").to_s, err: (testpath/"bgtail.err").to_s
    begin
      Timeout.timeout(60) { Process.wait(pid) }
      assert_equal 0, $CHILD_STATUS.exitstatus

      log = Dir[testpath/"log/bgtail/*.log"].first
      refute_nil log, "bgtail started no job: #{(testpath/"bgtail.err").read}"
      assert_equal marker, File.read(log).strip
    ensure
      begin
        Process.kill("TERM", pid)
        Process.wait(pid)
      rescue Errno::ESRCH, Errno::ECHILD
        nil
      end
    end
  end
end
