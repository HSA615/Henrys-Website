(function() {
  const userAgent = navigator.userAgent || navigator.vendor || window.opera || "";
  const isIPhone = /iPhone|iPod/i.test(userAgent);
  const isAndroidPhone = /Android/i.test(userAgent) && /Mobile/i.test(userAgent);
  const isWindowsPhone = /Windows Phone/i.test(userAgent);
  const isOperaMini = /Opera Mini/i.test(userAgent);
  const isPhone = isIPhone || isAndroidPhone || isWindowsPhone || isOperaMini;

  if (isPhone) {
    document.documentElement.classList.add("is-phone");
  }
})();
