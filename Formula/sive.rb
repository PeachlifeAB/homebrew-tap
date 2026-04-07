class Sive < Formula
  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/archive/refs/tags/0.1.0.tar.gz"
  sha256 "5a2c20ab2e78df86d18967efe231bae84b2465eff07465e0f2090f16450d4080"
  license "MIT"

  depends_on "cryptography"
  depends_on "python@3.13"
  depends_on "uv" => :build

  def install
    system "uv", "pip", "install", "--no-deps", "--python", Formula["python@3.13"].opt_bin/"python3.13", "--prefix", prefix, "."
  end

  test do
    assert_match "sive", shell_output("#{bin}/sive --version")
  end
end
