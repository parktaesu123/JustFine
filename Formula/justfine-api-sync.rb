class JustfineApiSync < Formula
  include Language::Python::Virtualenv

  desc "Sync Spring API specs to Notion"
  homepage "https://github.com/parktaesu123/JustFine"
  head "https://github.com/parktaesu123/JustFine.git", branch: "main"

  depends_on "python@3.12"

  def install
    venv = virtualenv_create(libexec, Formula["python@3.12"].opt_bin/"python3")
    venv.pip_install_and_link buildpath
  end

  test do
    assert_match "justfine-api-sync", shell_output("#{bin}/justfine-api-sync --help")
  end
end
