/* Slide-over cart drawer — progressive enhancement over the plain cart forms.
   With JS off, "Add to cart" / "Remove" just submit and redirect to /cart/. */
(function () {
  "use strict";

  var drawer = document.getElementById("cart-drawer");
  var backdrop = document.getElementById("cart-drawer-backdrop");
  if (!drawer || !backdrop) return;

  var open = false;

  function getCookie(name) {
    var m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? m.pop() : "";
  }

  function setCounts(n) {
    document.querySelectorAll("[data-cart-count]").forEach(function (el) {
      el.textContent = n;
      el.hidden = !n;
      el.style.display = n ? "" : "none";
    });
  }

  function show() {
    if (open) return;
    open = true;
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(function () {
      backdrop.style.opacity = "1";
      drawer.style.transform = "translateX(0)";
    });
  }

  function hide() {
    if (!open) return;
    open = false;
    backdrop.style.opacity = "0";
    drawer.style.transform = "translateX(100%)";
    document.body.style.overflow = "";
    setTimeout(function () {
      if (open) return;
      backdrop.hidden = true;
      drawer.hidden = true;
    }, 220);
  }

  function fill(html) {
    drawer.innerHTML = html;
  }

  function fetchJSON(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ "X-Requested-With": "fetch" }, opts.headers || {});
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (data) { return { ok: r.ok, data: data }; });
    });
  }

  // ── Open triggers ──
  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-cart]");
    if (opener) {
      e.preventDefault();
      // The drawer is pre-rendered server-side, so opening is instant — no fetch.
      show();
      // Refresh in the background in case the cart changed in another tab.
      fetchJSON("/cart/drawer/")
        .then(function (res) {
          if (res && res.data && res.data.html) {
            fill(res.data.html);
            if (typeof res.data.count === "number") setCounts(res.data.count);
          }
        })
        .catch(function () {});
      return;
    }
    if (e.target.closest("[data-close-cart]") || e.target === backdrop) {
      hide();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && open) hide();
  });

  // ── Add to cart (any storefront page) ──
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var isAdd = form.matches && form.matches('form[action*="/cart/add/"]');
    var isDrawerForm = form.matches && form.matches("[data-cart-form]");
    if (!isAdd && !isDrawerForm) return;

    e.preventDefault();
    var token = (form.querySelector('[name=csrfmiddlewaretoken]') || {}).value || getCookie("csrftoken");
    var btn = form.querySelector('[type=submit]');
    if (btn) btn.disabled = true;

    fetchJSON(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(new FormData(form)).toString(),
    }).then(function (res) {
      if (btn) btn.disabled = false;
      if (!res.ok) {
        if (isAdd) alert(res.data.error || "Could not add to cart.");
        return;
      }
      fill(res.data.html);
      setCounts(res.data.count);
      show();
    }).catch(function () {
      if (btn) btn.disabled = false;
      form.submit(); // hard fallback
    });
  });
})();
