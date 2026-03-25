class Lgtvctrl < Formula
  desc "Command-line control for LG WebOS TVs"
  homepage "https://github.com/PeachlifeAB/lgtvctrl"
  url "https://github.com/PeachlifeAB/lgtvctrl/archive/refs/tags/v0.6.4.tar.gz"
  sha256 "" # TODO: fill in after tagging and pushing to GitHub
  license "MIT"

  depends_on "python@3.13"
  depends_on "uv" => :build
  depends_on :macos

  def install
    system "uv", "pip", "install", "--no-deps", "--python", Formula["python@3.13"].opt_bin/"python3.13", "--prefix", prefix, "."
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/tv --version")
  end
end
