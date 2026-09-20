class Sive < Formula
  include Language::Python::Virtualenv

  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/homebrew-tap/releases/download/sive-0.1.9/sive-0.1.9.tar.gz"
  sha256 "a450ef59ac9ce2ab65b96c37d7c407c8920dac90eb91eec1f18e9f09ba6ffde9"
  license "MIT"

  livecheck do
    url :stable
    strategy :github_releases
    regex(/^sive-v?(\d+(?:\.\d+)+)$/i)
  end

  depends_on "bitwarden-cli"
  depends_on "cryptography"
  depends_on :macos
  depends_on "mise"
  depends_on "python@3.13"

  pypi_packages exclude_packages: "cryptography"

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
    assert_equal "sive #{version}", shell_output("#{bin}/sive --version").strip

    # `--version` imports only the stdlib, so it passes with cryptography
    # missing. `_mise-env` is the shell-startup hot path and is contractually
    # hermetic: no network, no vault, always exit 0.
    require "timeout"

    output = nil
    Timeout.timeout(60) do
      output = shell_output("#{bin}/sive _mise-env --tag brew-runtime-proof 2>&1")
    end
    assert_match "{}", output
    refute_match "Traceback", output

    # The snapshot round-trip is what actually loads cryptography; the hot path
    # above short-circuits before decrypting when no snapshot exists.
    (testpath/"roundtrip.py").write <<~PYTHON
      from sive.core.snapshot_crypto import decrypt_env, encrypt_env

      key = b"0" * 32
      env = {"SIVE_BREW_TEST": "ok"}
      assert decrypt_env(encrypt_env(env, key), key) == env
      print("round-trip ok")
    PYTHON
    assert_equal "round-trip ok",
                 shell_output("#{libexec}/bin/python #{testpath}/roundtrip.py").strip
  end
end
