class Lgtvctrl < Formula
  include Language::Python::Virtualenv

  desc "Command-line control for LG WebOS TVs"
  homepage "https://github.com/PeachlifeAB/lgtvctrl"
  url "https://github.com/PeachlifeAB/homebrew-tap/releases/download/lgtvctrl-0.1.1/lgtvctrl-0.1.1.tar.gz"
  sha256 "7de711acacd2c5e7f39d4065e146e7832414336045bf16323949c3a84ab73b2b"
  license "MIT"

  livecheck do
    url :stable
    strategy :github_releases
    regex(/^lgtvctrl-v?(\d+(?:\.\d+)+)$/i)
  end

  depends_on "openssl@3"
  depends_on "python@3.13"

  # Build backend. Homebrew's python vendors only pip and wheel, and the build
  # sandbox has no network, so an isolated build cannot fetch it. Same reason
  # `httpie` and 76 other core formulae vendor it.
  resource "setuptools" do
    url "https://files.pythonhosted.org/packages/34/26/f5d29e25ffdb535afef2d35cdb55b325298f96debd670da4c325e08d70f4/setuptools-83.0.0.tar.gz"
    sha256 "025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef"
  end

  # Build-only: poetry-core is the build backend for wakeonlan
  resource "poetry-core" do
    url "https://files.pythonhosted.org/packages/10/48/5b4f344c252ee2f75051b6bf7dfb68ab53aa00a107f5f8e5cbf795701dad/poetry_core-2.3.2.tar.gz"
    sha256 "20cb71be27b774628da9f384effd9183dfceb53bcef84063248a8672aa47031f"
  end

  resource "bscpylgtv" do
    url "https://files.pythonhosted.org/packages/a0/f8/9478424d0f40cbacfb944f9283149a4b3aabe28cebc97bf79f8dbfd286ed/bscpylgtv-0.5.3.tar.gz"
    sha256 "8c2f1b954cd6f14207c6b976dc2688ede6fd9f0dbaae67d26a87453debd1f68b"
  end

  resource "websockets" do
    url "https://files.pythonhosted.org/packages/04/24/4b2031d72e840ce4c1ccb255f693b15c334757fc50023e4db9537080b8c4/websockets-16.0.tar.gz"
    sha256 "5f6261a5e56e8d5c42a4497b364ea24d94d9563e8fbd44e78ac40879c60179b5"
  end

  resource "sqlitedict" do
    url "https://files.pythonhosted.org/packages/12/9a/7620d1e9dcb02839ed6d4b14064e609cdd7a8ae1e47289aa0456796dd9ca/sqlitedict-2.1.0.tar.gz"
    sha256 "03d9cfb96d602996f1d4c2db2856f1224b96a9c431bdd16e78032a72940f9e8c"
  end

  resource "wakeonlan" do
    url "https://files.pythonhosted.org/packages/ec/98/b92125baeaf67b3a838bfdb4ac4e685c793ce2771686b10df44275e424a4/wakeonlan-3.1.0.tar.gz"
    sha256 "aa12edc2587353528a89ad58a54c63212dc2a12226c186b7fcc02caa162cd962"
  end

  def install
    venv = virtualenv_create(libexec, "python3.13")
    venv.pip_install resources
    venv.pip_install_and_link buildpath, build_isolation: false
  end

  test do
    assert_equal "tv #{version}", shell_output("#{bin}/tv --version").strip

    # Every command that does real work needs a TV on the network, so startup
    # proves the parser and declared runtime dependencies load without one.
    require "timeout"

    output = nil
    Timeout.timeout(60) { output = shell_output("#{bin}/tv --help 2>&1") }
    assert_match "Control LG TV", output
    refute_match "Traceback", output

    (testpath/"imports.py").write <<~PYTHON
      import bscpylgtv

      print("deps ok")
    PYTHON
    assert_equal "deps ok",
                 shell_output("#{libexec}/bin/python #{testpath}/imports.py").strip
  end
end
