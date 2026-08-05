class Lgtvctrl < Formula
  include Language::Python::Virtualenv

  desc "Command-line control for LG WebOS TVs"
  homepage "https://github.com/PeachlifeAB/lgtvctrl"
  url "https://github.com/PeachlifeAB/lgtvctrl/archive/refs/tags/0.1.0.tar.gz"
  sha256 "4cf44bbda27c8828c6dc68e54ccb9dfc6852cdbad04fd943ef8d5efbdab16d72"
  license "MIT"

  bottle do
    root_url "https://github.com/PeachlifeAB/homebrew-tap/releases/download/lgtvctrl-0.1.0"
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "e7669fd8c1e14ff14f4e8c32eb6c9ac25ad25b61d69a6647f441886966dff6ab"
  end

  depends_on "python-setuptools" => :build
  depends_on :macos
  depends_on "openssl@3"
  depends_on "python@3.13"

  # Build-only: poetry-core is the build backend for wakeonlan
  resource "poetry-core" do
    url "https://files.pythonhosted.org/packages/10/48/5b4f344c252ee2f75051b6bf7dfb68ab53aa00a107f5f8e5cbf795701dad/poetry_core-2.3.2.tar.gz"
    sha256 "20cb71be27b774628da9f384effd9183dfceb53bcef84063248a8672aa47031f"
  end

  resource "bscpylgtv" do
    url "https://files.pythonhosted.org/packages/95/f5/f66b98534a464fc80fcc5cd4e3375e734c31e276613fab1f199470bda01f/bscpylgtv-0.5.1.tar.gz"
    sha256 "69cb7faea9024bfaac19844479e36c13515922d68c6e78885e5678514fe2640f"
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

  # pyobjc packages use pre-built wheels because pyobjc 12.1 source fails
  # to compile on macOS 15+ (CGWindowListCreateImageFromArray obsoleted).
  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/f4/d2/29e5e536adc07bc3d33dd09f3f7cf844bf7b4981820dc2a91dd810f3c782/pyobjc_core-12.1-cp313-cp313-macosx_10_13_universal2.whl"
    sha256 "01c0cf500596f03e21c23aef9b5f326b9fb1f8f118cf0d8b66749b6cf4cbb37a"
  end

  resource "pyobjc-framework-Cocoa" do
    url "https://files.pythonhosted.org/packages/ad/31/0c2e734165abb46215797bd830c4bdcb780b699854b15f2b6240515edcc6/pyobjc_framework_cocoa-12.1-cp313-cp313-macosx_10_13_universal2.whl"
    sha256 "5a3dcd491cacc2f5a197142b3c556d8aafa3963011110102a093349017705118"
  end

  resource "pyobjc-framework-Quartz" do
    url "https://files.pythonhosted.org/packages/ba/2d/e8f495328101898c16c32ac10e7b14b08ff2c443a756a76fd1271915f097/pyobjc_framework_quartz-12.1-cp313-cp313-macosx_10_13_universal2.whl"
    sha256 "629b7971b1b43a11617f1460cd218bd308dfea247cd4ee3842eb40ca6f588860"
  end

  def install
    # Remove setuptools-scm build requirement and use static version
    inreplace "pyproject.toml" do |s|
      s.gsub! 'requires = ["setuptools>=80.0", "setuptools-scm>=8"]',
              'requires = ["setuptools>=80.0"]'
      s.gsub! 'dynamic = ["version"]', ""
    end
    inreplace "pyproject.toml", /^\[project\]\nname = "lgtvctrl"\n/,
              "[project]\nname = \"lgtvctrl\"\nversion = \"#{version}\"\n"

    ENV["SETUPTOOLS_SCM_PRETEND_VERSION"] = version.to_s

    python = formula_opt_bin("python@3.13")/"python3.13"
    venv = virtualenv_create(libexec, "python3.13")
    venv_python = libexec/"bin/python"

    # 1. Install poetry-core first (build backend for wakeonlan)
    venv.pip_install resource("poetry-core"), build_isolation: false

    # 2. Install pyobjc wheels via cached_download + symlink.
    #    Platform-specific wheels (.whl) are zip archives that resource.stage
    #    would extract, breaking pip.  Use cached_download to get the raw file.
    %w[pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz].each do |name|
      r = resource(name)
      r.fetch
      whl_link = buildpath/r.downloader.basename
      ln_s r.cached_download, whl_link
      system python, "-m", "pip", "--python", venv_python,
             "install", "--no-deps", whl_link
    end

    # 3. Install remaining pure Python/sdist resources
    sdist_resources = resources.reject do |r|
      %w[poetry-core pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz].include?(r.name)
    end
    venv.pip_install sdist_resources, build_isolation: false

    # 4. Install main package and link bin scripts
    venv.pip_install_and_link buildpath, build_isolation: false
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/tv --version")
  end
end
