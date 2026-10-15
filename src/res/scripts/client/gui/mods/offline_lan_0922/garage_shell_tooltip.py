"""Add shot velocity to the #1513 native garage shell parameter blocks."""

import math


def _text(value):
    return value.decode('utf-8') if isinstance(value, bytes) else value


class GarageShellTooltipPatch(object):
    def __init__(self, module, number_format):
        self._module = module
        self._number_format = number_format
        self._patches = []
        self._warned = False

    def _insert(self, constructor, blocks, advanced=False):
        module = self._module
        damage_names = tuple(_text(module.text_styles.main(module._ms(
            '#menu:moduleInfo/params/' + name)))
            for name in ('damage', 'avgDamage'))
        speed_label = u'\u70ae\u5f39\u901f\u5ea6'.encode('utf-8')
        speed_name = _text(module.text_styles.main(speed_label))
        # Both native detailed constructors return parameter dictionaries with
        # data.name. Use the native label, not an assumed fixed row number.
        damage_index = None
        for index, block in enumerate(blocks):
            name = _text(block.get('data', {}).get('name', ''))
            if name.startswith(speed_name):
                return blocks
            if name.startswith(damage_names):
                damage_index = index
        if damage_index is None:
            return blocks
        vehicle = constructor.configuration.vehicle
        descriptor = getattr(vehicle, 'descriptor', None)
        gun = getattr(descriptor, 'gun', None)
        shell = constructor.shell.descriptor
        shell_cd = getattr(shell, 'compactDescr', None)
        for shot in getattr(gun, 'shots', ()):
            # #1513 GunShot is attribute-only; its legacy dict API raises.
            candidate = shot.shell
            if not (candidate is shell or (shell_cd is not None and
                    candidate.compactDescr == shell_cd)):
                continue
            speed = float(shot.speed)
            if speed <= 0 or math.isnan(speed) or math.isinf(speed):
                return blocks
            value = self._number_format(int(round(speed)))
            # Match #1513 shellComparator (first/default shot) and
            # shellOnVehicleComparator (the vehicle's active shot) without
            # changing activeGunShotIndex or the native parameter registry.
            shots = gun.shots
            baseline_index = (getattr(descriptor, 'activeGunShotIndex', None)
                              if advanced else 0)
            if (isinstance(baseline_index, int) and
                    0 <= baseline_index < len(shots)):
                baseline = float(shots[baseline_index].speed)
                if (baseline > 0 and not math.isnan(baseline) and
                        not math.isinf(baseline) and speed != baseline):
                    # Native BASE_SCHEME is worse/normal/better. Keep native
                    # fonts, colors and any accessibility theme overrides.
                    scheme = module.params_formatters.BASE_SCHEME
                    value = scheme[2 if speed > baseline else 0](value)
            row = constructor._packParameterBlock(
                speed_label, value,
                u' (\u7c73/\u79d2)'.encode('utf-8'))
            blocks.insert(damage_index + 1, row)
            break
        return blocks

    def _wrap(self, original, advanced):
        patch = self

        def construct(constructor):
            blocks = original(constructor)
            try:
                return patch._insert(constructor, blocks, advanced)
            except Exception as error:
                # Optional tooltip enrichment must not break the native view.
                if not patch._warned:
                    patch._warned = True
                    print('[Offline LAN 0.9.22] garage shell speed unavailable: '
                          '%s' % error)
                return blocks
        return construct

    def install(self):
        if self._patches:
            return
        for owner, advanced in (
                (self._module.CommonStatsBlockConstructor, False),
                (self._module._AdvancedCommonStatsBlockConstructior, True)):
            original = owner.__dict__['construct']
            wrapper = self._wrap(original, advanced)
            self._patches.append((owner, original, wrapper))
            owner.construct = wrapper

    def uninstall(self):
        for owner, original, wrapper in reversed(self._patches):
            if owner.__dict__.get('construct') is wrapper:
                owner.construct = original
        self._patches = []
