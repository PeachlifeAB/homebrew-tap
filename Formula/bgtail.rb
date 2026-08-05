class Bgtail < Formula
  desc "Run long-running commands detached with minimal heartbeat"
  homepage "https://github.com/PeachlifeAB/bgtail"
  url "https://github.com/PeachlifeAB/bgtail/archive/refs/tags/0.1.1.tar.gz"
  sha256 "04e923bd2a1122d3d4e702dba826093006576e8c80f88937bd13958c194b2670"
  license "MIT"

  bottle do
    root_url "https://github.com/PeachlifeAB/homebrew-tap/releases/download/bgtail-0.1.1"
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "33b64c9a2d4a55859d72c00c31660201f0159faca845c42e8ebbe5a779046077"
  end

  depends_on "uv" => :build
  depends_on :macos
  depends_on "python@3.13"

  def install
    python = formula_opt_bin("python@3.13")/"python3.13"
    system "uv", "pip", "install", "--no-deps", "--python", python, "--prefix", prefix, "."
  end

  test do
    assert_match "0.1.1", shell_output("#{bin}/bgtail --version")
  end
end
