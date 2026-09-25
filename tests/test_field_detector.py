from scrapling.parser import Adaptor

from core.field_detector import FieldDetector


def test_honeypot_filtering():
    """Honeypot inputs (hidden, display:none, offscreen) must be rejected."""
    html = """
    <form>
        <!-- Honeypots -->
        <input type="hidden" name="csrf_token" value="xyz123">
        <input type="text" name="user_trap" style="display:none" value="">
        <input type="text" name="email_trap" style="visibility:hidden" value="">
        <input type="text" name="hp_field" class="honeypot" value="">
        <input type="text" name="offscreen_trap" style="position:absolute; left:-9999px" value="">
        <input type="text" name="aria_trap" aria-hidden="true" value="">

        <!-- Legitimate Fields -->
        <input id="user_field" type="email" name="real_user" autocomplete="username">
        <input id="pass_field" type="password" name="real_password" autocomplete="current-password">
        <button id="btn_submit" type="submit">Sign In</button>
    </form>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["username"] is not None
    assert fields["password"] is not None
    assert fields["submit"] is not None

    # Verify that the resolved selectors point to the legitimate fields, NOT the honeypots
    user_el = page.css(fields["username"])[0]
    pass_el = page.css(fields["password"])[0]
    sub_el = page.css(fields["submit"])[0]

    assert user_el.attrib.get("name") == "real_user"
    assert pass_el.attrib.get("name") == "real_password"
    assert sub_el.attrib.get("id") == "btn_submit"


def test_standard_single_step_login():
    """Type 1: Single-step login form detection."""
    html = """
    <form action="/login" method="post">
        <label for="usr">Email</label>
        <input id="usr" type="text" name="email" placeholder="Enter your email">
        <label for="pwd">Password</label>
        <input id="pwd" type="password" name="password" placeholder="Password">
        <button type="submit">Log In</button>
    </form>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["username"] is not None
    assert fields["password"] is not None
    assert fields["submit"] is not None
    assert fields["next-button"] is None
    assert fields["modal-trigger"] is None


def test_multi_step_split_login():
    """Type 2: Step 1 shows username + Next button (no password yet)."""
    html = """
    <div class="split-login">
        <h2>Sign in to your account</h2>
        <input type="text" name="identifier" autocomplete="username" placeholder="Phone, email, or username">
        <button type="button" class="next-btn">Next</button>
    </div>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["username"] is not None
    assert fields["password"] is None
    assert fields["next-button"] is not None
    assert fields["submit"] is None


def test_modal_trigger_detection():
    """Type 3: Page load has no inputs, only a 'Sign In' modal trigger button."""
    html = """
    <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <button aria-haspopup="dialog" class="auth-btn">Sign In</button>
    </nav>
    <main>
        <h1>Welcome to our site</h1>
    </main>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["username"] is None
    assert fields["password"] is None
    assert fields["modal-trigger"] is not None


def test_web_components_and_custom_tags():
    """Type 4/Custom: Reddit-style web component inputs."""
    html = """
    <shreddit-app>
        <faceplate-text-input name="username" autocomplete="username webauthn" label="Username"></faceplate-text-input>
        <faceplate-text-input name="password" type="password" autocomplete="current-password" label="Password"></faceplate-text-input>
        <button type="submit">Log In</button>
    </shreddit-app>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["username"] is not None
    assert fields["password"] is not None
    assert fields["submit"] is not None


def test_ancestor_honeypot_filtering():
    """Inputs inside hidden/display:none ancestor containers must be filtered out."""
    html = """
    <form>
        <div style="display:none">
            <input type="text" name="trap_in_hidden_div">
        </div>
        <div hidden>
            <input type="email" name="trap_in_hidden_attr">
        </div>
        <input id="real_user" type="text" name="user" autocomplete="username">
        <input id="real_pass" type="password" name="password">
        <button type="submit">Sign In</button>
    </form>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    user_el = page.css(fields["username"])[0]
    assert user_el.attrib.get("id") == "real_user"


def test_nested_span_button_text_matching():
    """Buttons with text inside nested <span> or child tags must match."""
    html = """
    <form>
        <input type="email" name="email">
        <input type="password" name="password">
        <button class="btn">
            <span class="icon"></span>
            <span class="label">Sign In</span>
        </button>
    </form>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["submit"] is not None


def test_form_scoped_submit_button():
    """Submit button inside the login form must be preferred over preceding forms."""
    html = """
    <!-- Preceding newsletter form -->
    <form id="newsletter">
        <input type="text" name="email_newsletter">
        <button id="btn_newsletter" type="submit">Subscribe</button>
    </form>

    <!-- Actual login form -->
    <form id="login">
        <input id="usr" type="email" autocomplete="username">
        <input id="pwd" type="password" autocomplete="current-password">
        <button id="btn_login" type="submit">Log In</button>
    </form>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    sub_el = page.css(fields["submit"])[0]
    assert sub_el.attrib.get("id") == "btn_login"


def test_search_input_does_not_block_modal_trigger():
    """An unrelated search box on a page must not prevent modal trigger detection."""
    html = """
    <header>
        <input type="text" name="q" placeholder="Search the store">
        <button aria-haspopup="dialog" class="auth-trigger">Sign In</button>
    </header>
    <main>
        <h1>Store Products</h1>
    </main>
    """
    page = Adaptor(html)
    fields = FieldDetector.detect_fields(page)

    assert fields["modal-trigger"] is not None
    assert fields["username"] is None
    assert fields["password"] is None
