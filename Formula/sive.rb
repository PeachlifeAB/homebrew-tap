class Sive < Formula
  include Language::Python::Virtualenv

  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/releases/download/v0.1.6/sive-0.1.6.tar.gz"
  sha256 "5affae1a9a7decfe5ef82e98c841665b44d5fac77babb123c4484f72bb3e6123"
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
