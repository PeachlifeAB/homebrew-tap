class Sive < Formula
  include Language::Python::Virtualenv

  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/homebrew-tap/releases/download/sive-0.1.13/sive-0.1.13.tar.gz"
  sha256 "833b22e421ed552745753bb882282afbcc7a95e283a9f024e0a208f3aad0fe35"
  license "MIT"

  livecheck do
    url :stable
    strategy :github_releases
    regex(/^sive-v?(\d+(?:\.\d+)+)$/i)
  end

  depends_on "bitwarden-cli"
  depends_on "cryptography"
  depends_on "mise"
  depends_on "python@3.14"

  on_macos do
    depends_on arch: :arm64
  end

  on_linux do
    resource "jaraco-classes" do
      url "https://files.pythonhosted.org/packages/06/c0/ed4a27bc5571b99e3cff68f8a9fa5b56ff7df1c2251cc715a652ddd26402/jaraco.classes-3.4.0.tar.gz"
      sha256 "47a024b51d0239c0dd8c8540c6c7f484be3b8fcf0b2d85c13825780d3b3f3acd"
    end

    resource "jaraco-context" do
      url "https://files.pythonhosted.org/packages/af/50/4763cd07e722bb6285316d390a164bc7e479db9d90daa769f22578f698b4/jaraco_context-6.1.2.tar.gz"
      sha256 "f1a6c9d391e661cc5b8d39861ff077a7dc24dc23833ccee564b234b81c82dfe3"
    end

    resource "jaraco-functools" do
      url "https://files.pythonhosted.org/packages/6c/1f/c23395957d41ccf27c4e535c3d334c4051e5395b3752057ba4cbaec35c56/jaraco_functools-4.6.0.tar.gz"
      sha256 "880c577ec9720b3a052d5bc611fb9f2269b3d87902ef42440df443b88e443280"
    end

    resource "jeepney" do
      url "https://files.pythonhosted.org/packages/7b/6f/357efd7602486741aa73ffc0617fb310a29b588ed0fd69c2399acbb85b0c/jeepney-0.9.0.tar.gz"
      sha256 "cf0e9e845622b81e4a28df94c40345400256ec608d0e55bb8a3feaa9163f5732"
    end

    resource "keyring" do
      url "https://files.pythonhosted.org/packages/43/4b/674af6ef2f97d56f0ab5153bf0bfa28ccb6c3ed4d1babf4305449668807b/keyring-25.7.0.tar.gz"
      sha256 "fe01bd85eb3f8fb3dd0405defdeac9a5b4f6f0439edbb3149577f244a2e8245b"
    end

    resource "more-itertools" do
      url "https://files.pythonhosted.org/packages/52/b8/c63995bebbb9ac9c059350e0fb8c82c2420c85aeca7d34e40aecf3df9281/more_itertools-11.2.1.tar.gz"
      sha256 "cbf08fd0af284dc69718b9b76a8e6203df624d70209ea511e4219d350c856f63"
    end

    resource "secretstorage" do
      url "https://files.pythonhosted.org/packages/1c/03/e834bcd866f2f8a49a85eaff47340affa3bfa391ee9912a952a1faa68c7b/secretstorage-3.5.0.tar.gz"
      sha256 "f04b8e4689cbce351744d5537bf6b1329c6fc68f91fa666f60a380edddcd11be"
    end
  end

  pypi_packages exclude_packages: "cryptography"

  resource "setuptools" do
    url "https://files.pythonhosted.org/packages/34/26/f5d29e25ffdb535afef2d35cdb55b325298f96debd670da4c325e08d70f4/setuptools-83.0.0.tar.gz"
    sha256 "025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef"
  end

  allow_network_access! :build
  def install
    venv = virtualenv_create(libexec, "python3.14")
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
