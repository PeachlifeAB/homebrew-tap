class Bgtail < Formula
  desc "Run long-running commands detached with minimal heartbeat"
  homepage "https://github.com/PeachlifeAB/bgtail"
  url "https://github.com/PeachlifeAB/bgtail/archive/refs/tags/0.1.0.tar.gz"
  sha256 "30007b93c81602c2b764253faeb69a8ff5e85ce56bb191e426ae61231afbf509"
  license "MIT"

  depends_on "uv" => :build
  depends_on :macos
  depends_on "python@3.13"

  def install
    python = Formula["python@3.13"].opt_bin/"python3.13"
    system "uv", "pip", "install", "--no-deps", "--python", python, "--prefix", prefix, "."
  end

  test do
    assert_match "bgtail", shell_output("#{bin}/bgtail --version")
  end
end
