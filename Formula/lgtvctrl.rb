class Lgtvctrl < Formula
  include Language::Python::Virtualenv

  desc "Command-line control for LG WebOS TVs"
  homepage "https://github.com/PeachlifeAB/lgtvctrl"
  url "https://github.com/PeachlifeAB/lgtvctrl/archive/refs/tags/0.1.0.tar.gz"
  sha256 "4cf44bbda27c8828c6dc68e54ccb9dfc6852cdbad04fd943ef8d5efbdab16d72"
  license "MIT"

  depends_on "python-setuptools" => :build
  depends_on :macos
  depends_on "openssl@3"
  depends_on "python@3.13"

  resource "bscpylgtv" do
    url "https://files.pythonhosted.org/packages/5f/e2/c0d3e0e8945783b58ee20d7855f285b9dcb1bf19cb44384b42c20afd533a/bscpylgtv-0.5.1-py3-none-any.whl"
    sha256 "842a545ed19ed16b5fe9006184ef917ff88ed140219aea680aedd8b56375d52d"
  end

  resource "websockets" do
    url "https://files.pythonhosted.org/packages/6f/28/258ebab549c2bf3e64d2b0217b973467394a9cea8c42f70418ca2c5d0d2e/websockets-16.0-py3-none-any.whl"
    sha256 "1637db62fad1dc833276dded54215f2c7fa46912301a24bd94d45d46a011ceec"
  end

  resource "sqlitedict" do
    url "https://files.pythonhosted.org/packages/12/9a/7620d1e9dcb02839ed6d4b14064e609cdd7a8ae1e47289aa0456796dd9ca/sqlitedict-2.1.0.tar.gz"
    sha256 "03d9cfb96d602996f1d4c2db2856f1224b96a9c431bdd16e78032a72940f9e8c"
  end

  resource "wakeonlan" do
    url "https://files.pythonhosted.org/packages/e9/47/99a02d847104bbc08d10b147e77593c127c405774fa7f5247afd152754e5/wakeonlan-3.1.0-py3-none-any.whl"
    sha256 "9414da87f48e5dc8a1bb0fa15aba5a0079cfd014231c4cc8e6f2477a0d078c7e"
  end

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
    # (setuptools-scm needs network access to install, which Homebrew blocks)
    inreplace "pyproject.toml" do |s|
      s.gsub! 'requires = ["setuptools>=80.0", "setuptools-scm>=8"]',
              'requires = ["setuptools>=80.0"]'
      s.gsub! 'dynamic = ["version"]', ""
    end
    inreplace "pyproject.toml", /^\[project\]\nname = "lgtvctrl"\n/,
              "[project]\nname = \"lgtvctrl\"\nversion = \"#{version}\"\n"

    ENV["SETUPTOOLS_SCM_PRETEND_VERSION"] = version.to_s
    venv = virtualenv_create(libexec, "python3.13")
    python = Formula["python@3.13"].opt_bin/"python3.13"
    venv_python = libexec/"bin/python"

    # Install all wheel resources via cached_download.  Homebrew's
    # resource.stage extracts .whl (zip) files, which breaks pip, so we
    # symlink the cached download to a clean filename and pip-install that.
    %w[pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz
       bscpylgtv websockets wakeonlan].each do |name|
      r = resource(name)
      r.fetch
      whl_link = buildpath/r.downloader.basename
      ln_s r.cached_download, whl_link
      system python, "-m", "pip", "--python", venv_python,
             "install", "--no-deps", whl_link
    end

    # sqlitedict is a single-file pure-Python package (no wheel on PyPI).
    # Copy it directly into site-packages to avoid needing setuptools.
    resource("sqlitedict").stage do
      venv.site_packages.install "sqlitedict.py"
    end

    # Install main package and link bin scripts.
    # build_isolation: false uses setuptools from python-setuptools dep
    # (available via --system-site-packages) instead of downloading from PyPI.
    venv.pip_install_and_link(buildpath, build_isolation: false)
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/tv --version")
  end
end
