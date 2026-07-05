/* PrivacyUI — pure computation of every visual state the privacy controls
   can be in, from the backend's privacy payload. Kept DOM-free so the exact
   logic the page runs is unit-testable in node (desktop/tests/ui). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) { module.exports = factory(); }
  else { root.PrivacyUI = factory(); }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /**
   * @param privacy  backend payload: { processing_mode, env_locked, cloud_ack }
   * @param t        translate fn (key) -> string|null; optional
   * @returns everything the settings panel + top-bar chip need to render
   */
  function compute(privacy, t) {
    privacy = privacy || {};
    t = t || function () { return null; };
    var local = privacy.processing_mode === 'local_only';
    return {
      localOnly: local,
      badgeClass: 'engine-status-badge ' +
        (local ? 'engine-status-offline' : 'engine-status-online'),
      statusText: local
        ? (t('settings_mode_local') || '🔒 Local only — nothing is sent to the cloud')
        : (t('settings_mode_cloud') || '☁ Cloud processing allowed'),
      btnLabel: local
        ? (t('settings_enable_cloud') || 'Allow cloud processing…')
        : (t('settings_disable_cloud') || 'Switch to Local only'),
      btnDisabled: !!privacy.env_locked,
      // The button acts as a "Local only" toggle: pressed = local-only active.
      ariaPressed: local ? 'true' : 'false',
      note: privacy.env_locked
        ? (t('settings_env_locked') ||
           'Set by ALLOW_CLOUD in .env — remove it there to control this here.')
        : '',
      // What a click means next (flips the mode).
      enableCloudOnClick: local,
      // First-time cloud enable still needs the disclosure confirmation;
      // once acknowledged it is never asked again.
      needsAckOnEnable: !privacy.cloud_ack,
      chipText: local
        ? (t('privacy_chip_local') || '🔒 Local only')
        : (t('privacy_chip_cloud') || '☁ Cloud allowed'),
      // Cloud-provider key inputs/save/test are unavailable in local-only
      // mode (removal stays allowed — privacy-positive).
      providerControlsDisabled: local,
    };
  }

  return { compute: compute };
}));
