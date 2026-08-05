class Sive < Formula
  include Language::Python::Virtualenv

  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/releases/download/v0.1.8/sive-0.1.8.tar.gz"
  sha256 "6e59ac277dc133d88028683fed73f6906afd28cad4ad27084fd177ca2898840e"
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
