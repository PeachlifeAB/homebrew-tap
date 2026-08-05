class Sive < Formula
  include Language::Python::Virtualenv

  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/releases/download/v0.1.7/sive-0.1.7.tar.gz"
  sha256 "3fc8f41cb8709956c9e8c663a9583c8d78cfc39c0473d21cec9b1e9cbbe85139"
  license "MIT"

  depends_on "bitwarden-cli"
  depends_on "cryptography"
  depends_on "mise"
  depends_on "python@3.13"

  pypi_packages exclude_packages: "cryptography"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/sive --version")
  end
end
