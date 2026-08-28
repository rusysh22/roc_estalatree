(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var isCoarsePointer = window.matchMedia("(pointer: coarse)").matches;

  // ── Global loading / buffer indicator ─────────────────────────────────────
  // A slim top progress bar for full-page navigation (link clicks, form
  // submits) and htmx partial requests, plus a spinner injected into the
  // clicked submit button so buttons can't be double-clicked mid-request.
  function initLoadingIndicator() {
    var bar = document.getElementById("page-progress-bar");
    if (!bar) return;
    var hideTimer = null;

    function start() {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
      bar.classList.add("is-active");
      bar.style.width = "0%";
      void bar.offsetWidth; // force reflow so the width transition retriggers
      bar.style.width = "80%";
    }

    function done() {
      bar.style.width = "100%";
      hideTimer = setTimeout(function () {
        bar.classList.remove("is-active");
        bar.style.width = "0%";
      }, 250);
    }

    function isHtmxElement(el) {
      return !!(el.closest && el.closest("[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete]"));
    }

    function setButtonLoading(btn) {
      if (!btn || btn.dataset.loadingActive === "true") return;
      btn.dataset.loadingActive = "true";
      btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add("opacity-70", "cursor-not-allowed");
      btn.innerHTML = '<span class="btn-spinner" style="margin-right:.5em;"></span>' + btn.innerHTML;
    }

    function resetButton(btn) {
      if (!btn || btn.dataset.loadingActive !== "true") return;
      btn.disabled = false;
      btn.classList.remove("opacity-70", "cursor-not-allowed");
      btn.innerHTML = btn.dataset.originalHtml || btn.innerHTML;
      delete btn.dataset.loadingActive;
    }

    // Full-page navigation: same-origin link clicks (skip new tabs, downloads,
    // in-page anchors, and modified clicks that open in a new tab).
    document.addEventListener("click", function (e) {
      var link = e.target.closest && e.target.closest("a[href]");
      if (!link || isHtmxElement(link)) return;
      if (link.target && link.target !== "_self") return;
      if (link.hasAttribute("download")) return;
      var href = link.getAttribute("href") || "";
      if (!href || href.charAt(0) === "#" || href.indexOf("mailto:") === 0 || href.indexOf("tel:") === 0) return;
      if (link.origin !== window.location.origin) return;
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      start();
    });

    // Full-page navigation: regular (non-htmx) form submits.
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form || isHtmxElement(form) || form.hasAttribute("data-no-loading")) return;
      start();
      setButtonLoading(form.querySelector('button[type="submit"]:not([disabled])'));
    }, true);

    // htmx partial requests (dashboard / seller / console).
    document.body.addEventListener("htmx:beforeRequest", function () { start(); });
    document.body.addEventListener("htmx:afterRequest", function () { done(); });
    document.body.addEventListener("htmx:responseError", function () { done(); });
    document.body.addEventListener("htmx:sendError", function () { done(); });

    // Restore any spinner-ified buttons if the page is served from bfcache
    // (back/forward navigation) so a stale disabled state never lingers.
    window.addEventListener("pageshow", function () {
      bar.classList.remove("is-active");
      bar.style.width = "0%";
      document.querySelectorAll('[data-loading-active="true"]').forEach(resetButton);
    });
  }

  function initScrollReveal() {
    var items = document.querySelectorAll("[data-reveal]");
    if (!items.length) return;

    if (reduceMotion || !("IntersectionObserver" in window)) {
      items.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var delay = entry.target.getAttribute("data-reveal-delay") || 0;
          entry.target.style.animationDelay = delay + "ms";
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15, rootMargin: "0px 0px -40px 0px" });

    items.forEach(function (el) { observer.observe(el); });
  }

  function initMagneticButtons() {
    if (reduceMotion || isCoarsePointer) return;
    var buttons = document.querySelectorAll("[data-magnetic]");

    buttons.forEach(function (btn) {
      var strength = 18;
      btn.addEventListener("mousemove", function (e) {
        var rect = btn.getBoundingClientRect();
        var x = e.clientX - rect.left - rect.width / 2;
        var y = e.clientY - rect.top - rect.height / 2;
        btn.style.transform =
          "translate(" + (x / rect.width) * strength + "px, " + (y / rect.height) * strength + "px)";
      });
      btn.addEventListener("mouseleave", function () {
        btn.style.transform = "translate(0, 0)";
      });
    });
  }

  function initTiltCards() {
    if (reduceMotion || isCoarsePointer) return;
    var cards = document.querySelectorAll("[data-tilt]");

    cards.forEach(function (card) {
      var maxTilt = 6;
      card.addEventListener("mousemove", function (e) {
        var rect = card.getBoundingClientRect();
        var px = (e.clientX - rect.left) / rect.width - 0.5;
        var py = (e.clientY - rect.top) / rect.height - 0.5;
        card.style.transform =
          "perspective(800px) rotateX(" + (-py * maxTilt) + "deg) rotateY(" + (px * maxTilt) + "deg) translateZ(0)";
      });
      card.addEventListener("mouseleave", function () {
        card.style.transform = "perspective(800px) rotateX(0) rotateY(0)";
      });
    });
  }

  function initCountUp() {
    var counters = document.querySelectorAll("[data-countup]");
    if (!counters.length) return;

    function animateCounter(el) {
      var target = parseInt(el.getAttribute("data-countup"), 10) || 0;
      if (reduceMotion) {
        el.textContent = target.toLocaleString();
        return;
      }
      var duration = 1400;
      var start = null;

      function step(timestamp) {
        if (start === null) start = timestamp;
        var progress = Math.min((timestamp - start) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.floor(eased * target).toLocaleString();
        if (progress < 1) {
          window.requestAnimationFrame(step);
        } else {
          el.textContent = target.toLocaleString();
        }
      }
      window.requestAnimationFrame(step);
    }

    if (!("IntersectionObserver" in window)) {
      counters.forEach(animateCounter);
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    counters.forEach(function (el) { observer.observe(el); });
  }

  function initMobileNav() {
    var toggle = document.querySelector("[data-mobile-nav-toggle]");
    var panel = document.querySelector("[data-mobile-nav-panel]");
    if (!toggle || !panel) return;
    toggle.addEventListener("click", function () {
      var isOpen = panel.hasAttribute("hidden") === false;
      if (isOpen) {
        panel.setAttribute("hidden", "");
        toggle.setAttribute("aria-expanded", "false");
      } else {
        panel.removeAttribute("hidden");
        toggle.setAttribute("aria-expanded", "true");
      }
    });
  }

  function initPasswordToggle() {
    var buttons = document.querySelectorAll("[data-password-toggle]");
    buttons.forEach(function (btn) {
      var input = btn.parentElement.querySelector("input");
      var eyeOpen = btn.querySelector("[data-eye-open]");
      var eyeClosed = btn.querySelector("[data-eye-closed]");
      if (!input) return;
      btn.addEventListener("click", function () {
        var isPassword = input.type === "password";
        input.type = isPassword ? "text" : "password";
        btn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
        if (eyeOpen) eyeOpen.classList.toggle("hidden", isPassword);
        if (eyeClosed) eyeClosed.classList.toggle("hidden", !isPassword);
      });
    });
  }

  function initPaymentMethodGroups() {
    var toggles = document.querySelectorAll("[data-payment-toggle]");
    toggles.forEach(function (btn) {
      var group = btn.closest("[data-payment-group]");
      if (!group) return;
      var hiddenItems = group.querySelectorAll("[data-payment-extra]");
      var moreLabel = btn.getAttribute("data-more-label") || "Show more";
      var lessLabel = btn.getAttribute("data-less-label") || "Show less";
      btn.addEventListener("click", function () {
        var isOpen = group.getAttribute("data-open") === "true";
        group.setAttribute("data-open", isOpen ? "false" : "true");
        hiddenItems.forEach(function (el) {
          el.classList.toggle("hidden", isOpen);
        });
        btn.textContent = isOpen ? moreLabel : lessLabel;
      });
    });
  }

  function initFaqAccordion() {
    var items = document.querySelectorAll("[data-faq-item]");
    items.forEach(function (item) {
      var trigger = item.querySelector("[data-faq-trigger]");
      var panel = item.querySelector("[data-faq-panel]");
      if (!trigger || !panel) return;
      trigger.addEventListener("click", function () {
        var isOpen = item.getAttribute("data-open") === "true";
        items.forEach(function (other) {
          other.setAttribute("data-open", "false");
          var otherPanel = other.querySelector("[data-faq-panel]");
          if (otherPanel) otherPanel.style.maxHeight = "0px";
        });
        if (!isOpen) {
          item.setAttribute("data-open", "true");
          panel.style.maxHeight = panel.scrollHeight + "px";
        }
      });
    });
  }

  function formatRupiah(n) {
    return "Rp" + Math.max(0, Math.floor(n || 0)).toLocaleString("id-ID");
  }

  function initAmountFormatting() {
    var input = document.querySelector("[data-amount-input]");
    var preview = document.querySelector("[data-amount-preview]");
    var chips = document.querySelectorAll("[data-amount-chip]");
    if (!input) return;

    function syncChips() {
      var current = String(parseInt(input.value, 10) || "");
      chips.forEach(function (chip) {
        var match = chip.getAttribute("data-amount") === current;
        chip.classList.toggle("border-primary-500", match);
        chip.classList.toggle("bg-primary-50", match);
        chip.classList.toggle("text-primary-700", match);
      });
    }

    var feePercent = parseFloat(input.getAttribute("data-fee-percent")) || 0;
    var feeFlat = parseInt(input.getAttribute("data-fee-flat"), 10) || 0;

    function updatePreview() {
      if (preview) {
        var val = parseInt(input.value, 10);
        if (!val) {
          preview.textContent = "";
        } else if (feePercent || feeFlat) {
          var fee = Math.ceil(val * feePercent / 100) + feeFlat;
          preview.textContent =
            formatRupiah(val) + " + fee " + formatRupiah(fee) +
            " = " + formatRupiah(val + fee) + " to pay";
        } else {
          preview.textContent = formatRupiah(val);
        }
      }
      syncChips();
    }

    input.addEventListener("input", updatePreview);
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        input.value = chip.getAttribute("data-amount");
        updatePreview();
      });
    });
    updatePreview();
  }

  function initGenericAmountPreview() {
    var inputs = document.querySelectorAll("[data-format-idr]");
    inputs.forEach(function (input) {
      var preview = input.nextElementSibling;
      if (!preview || !preview.hasAttribute("data-format-idr-preview")) {
        preview = document.createElement("p");
        preview.setAttribute("data-format-idr-preview", "");
        preview.className = "text-xs font-semibold text-ink-500 mt-1";
        input.insertAdjacentElement("afterend", preview);
      }
      function update() {
        var val = parseInt(input.value, 10);
        preview.textContent = val ? formatRupiah(val) : "";
      }
      input.addEventListener("input", update);
      update();
    });
  }

  function initCopyButtons() {
    var buttons = document.querySelectorAll("[data-copy-trigger]");
    buttons.forEach(function (btn) {
      var row = btn.closest("[data-copy-row]");
      var valueEl = row && row.querySelector("[data-copy-value]");
      if (!valueEl) return;
      var label = btn.getAttribute("data-copy-label") || "Copy";
      var doneLabel = btn.getAttribute("data-copy-done-label") || "Copied!";
      btn.addEventListener("click", function () {
        var text = valueEl.textContent.trim();
        var done = function () {
          btn.textContent = doneLabel;
          setTimeout(function () { btn.textContent = label; }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, done);
        } else {
          var ta = document.createElement("textarea");
          ta.value = text;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand("copy"); } catch (err) { /* no-op */ }
          document.body.removeChild(ta);
          done();
        }
      });
    });
  }

  function initStarRating() {
    var groups = document.querySelectorAll("[data-star-rating]");
    groups.forEach(function (group) {
      var labels = Array.prototype.slice.call(group.querySelectorAll("label"));
      function paint(count) {
        labels.forEach(function (label, idx) {
          var star = label.querySelector("[data-star]");
          if (!star) return;
          star.classList.toggle("text-gold-500", idx < count);
          star.classList.toggle("text-ink-200", idx >= count);
        });
      }
      var checkedInput = group.querySelector("input[type=radio]:checked");
      paint(checkedInput ? parseInt(checkedInput.value, 10) : 0);

      labels.forEach(function (label, idx) {
        var input = label.querySelector("input[type=radio]");
        if (!input) return;
        label.addEventListener("mouseenter", function () { paint(idx + 1); });
        input.addEventListener("change", function () { paint(idx + 1); });
      });
      group.addEventListener("mouseleave", function () {
        var current = group.querySelector("input[type=radio]:checked");
        paint(current ? parseInt(current.value, 10) : 0);
      });
    });
  }

  function safeInit(fn) {
    try {
      fn();
    } catch (err) {
      if (window.console && console.error) console.error("site.js:", fn.name, err);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    safeInit(initLoadingIndicator);
    safeInit(initScrollReveal);
    safeInit(initMagneticButtons);
    safeInit(initTiltCards);
    safeInit(initCountUp);
    safeInit(initMobileNav);
    safeInit(initPasswordToggle);
    safeInit(initPaymentMethodGroups);
    safeInit(initFaqAccordion);
    safeInit(initCopyButtons);
    safeInit(initAmountFormatting);
    safeInit(initGenericAmountPreview);
    safeInit(initStarRating);
  });
})();
