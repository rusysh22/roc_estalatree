(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var isCoarsePointer = window.matchMedia("(pointer: coarse)").matches;

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

  function safeInit(fn) {
    try {
      fn();
    } catch (err) {
      if (window.console && console.error) console.error("site.js:", fn.name, err);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    safeInit(initScrollReveal);
    safeInit(initMagneticButtons);
    safeInit(initTiltCards);
    safeInit(initCountUp);
    safeInit(initMobileNav);
    safeInit(initPasswordToggle);
    safeInit(initFaqAccordion);
  });
})();
