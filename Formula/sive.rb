class Sive < Formula
  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/archive/refs/tags/0.1.2.tar.gz"
  sha256 "dee6b9bf8342e8777d202575a3ce59e9bfd817f8078bb8ff97b856ccd1717db4"
  license "MIT"

  depends_on "uv" => :build
  depends_on "cryptography"
  depends_on "python@3.13"

  def install
    python = Formula["python@3.13"].opt_bin/"python3.13"
    system "uv", "pip", "install", "--no-deps", "--python", python, "--prefix", prefix, "."
  end

  test do
    assert_match "sive", shell_output("#{bin}/sive --version")
  end
end
