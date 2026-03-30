class JustfineApiSync < Formula
  desc "Sync Spring API specs to Notion"
  homepage "https://github.com/parktaesu123/JustFine"
  head "https://github.com/parktaesu123/JustFine.git", branch: "main"

  depends_on "python@3.12"

  def install
    libexec.install "api_to_notion.py"
    (bin/"justfine-api-sync").write <<~EOS
      #!/bin/bash
      exec "#{Formula["python@3.12"].opt_bin}/python3" "#{libexec}/api_to_notion.py" "$@"
    EOS
    chmod 0755, bin/"justfine-api-sync"
  end

  test do
    assert_match "justfine-api-sync", shell_output("#{bin}/justfine-api-sync --help")
  end
end
