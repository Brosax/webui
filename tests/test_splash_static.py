from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SPLASH = REPO / "static" / "splash.html"


def test_splash_uses_jsdelivr_three():
    src = SPLASH.read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js" in src
    assert "cdnjs.cloudflare.com/ajax/libs/three.js" not in src


def test_splash_navigates_to_main_app_or_setup():
    src = SPLASH.read_text(encoding="utf-8")
    assert "window.location.href = '/setup-admin';" in src
    assert "window.location.href = '/index.html';" in src
    assert "login?next=" in src
    assert "/index.html" in src


def test_splash_is_centered_and_click_anywhere():
    src = SPLASH.read_text(encoding="utf-8")
    assert "bottom: 36px;" in src
    assert "transform: translateX(-50%);" in src
    assert "pointer-events: auto;" in src
    assert "document.addEventListener('click'" in src


def test_splash_mouse_interaction_is_stronger():
    src = SPLASH.read_text(encoding="utf-8")
    assert "mouseLight = new THREE.PointLight(colorPeak, 5.5, 160, 1.8);" in src
    assert "const targetCamX = (mouseWorld.x * 7);" in src
    assert "const targetCamY = (mouseWorld.y * 7);" in src
    assert "camera.position.x += (targetCamX - camera.position.x) * 0.035;" in src
    assert "camera.position.y += (targetCamY - camera.position.y) * 0.035;" in src
    assert "scene.rotation.x = Math.sin(now * 0.0003) * 0.08 + mouseWorld.y * 0.03;" in src
    assert "scene.rotation.y = Math.cos(now * 0.0002) * 0.08 + mouseWorld.x * 0.04;" in src
    assert "mouseLight.position.x += (mouseWorld.x * 18 - mouseLight.position.x) * 0.25;" in src
    assert "mouseLight.position.y += (mouseWorld.y * 12 - mouseLight.position.y) * 0.25;" in src
    assert "mouseLight.position.z = 18;" in src
