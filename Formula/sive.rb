class Sive < Formula
  desc "Sync secrets from your vault into your shell"
  homepage "https://github.com/PeachlifeAB/sive"
  url "https://github.com/PeachlifeAB/sive/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "987e9463c88f878238e50f9ca79933dc393057f6a2f743aae9d59518e2ef334f"
  license "MIT"

  depends_on "python@3.13"
  depends_on "uv" => :build

  def install
    system "uv", "pip", "install", "--no-deps", "--python", Formula["python@3.13"].opt_bin/"python3.13", "--prefix", prefix, "."
  end

  test do
    assert_match "sive", shell_output("#{bin}/sive --version")
  end
end
