class Sive < Formula
  include Language::Python::Virtualenv

  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/archive/refs/tags/0.1.4.tar.gz"
  sha256 "f99dc3928df4b2ff2ab64bb91845e8d0d2241fe3cd607ced0785f7866bcc5094"
  license "MIT"

  depends_on "bitwarden-cli"
  depends_on "cryptography"
  depends_on "mise"
  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/sive --version")
  end
end
