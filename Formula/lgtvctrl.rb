class Lgtvctrl < Formula
  desc "Command-line control for LG WebOS TVs"
  homepage "https://github.com/PeachlifeAB/lgtvctrl"
  url "https://github.com/PeachlifeAB/lgtvctrl/archive/refs/tags/0.1.0.tar.gz"
  sha256 "748fc418e617ecfc1c32ceac6ff15affeae88128c5b64365575b3de5c27408f0"
  license "MIT"

  depends_on "uv" => :build
  depends_on :macos
  depends_on "python@3.13"

  def install
    python = Formula["python@3.13"].opt_bin/"python3.13"
    system "uv", "pip", "install", "--no-deps", "--python", python, "--prefix", prefix, "."
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/tv --version")
  end
end
