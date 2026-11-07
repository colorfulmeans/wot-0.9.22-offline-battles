"""9.6 central-zone correction for the shared bounded shot cone.

Official base: https://worldoftanks.com/en/news/general-news/9-6-accuracy-changes/
https://lesta.ru/support/ru/products/mt/article/35718/
The inner 10%-radius zone changes from about 16% to 10%; removed probability
moves into its neighbouring zone. Exact within-zone sampling was not published.
Explicit reconstruction: retain the 8.6 bounded radial normal elsewhere and
redistribute rejected central samples uniformly into the 10%-20% radius band.
This preserves the published mass change, not a claimed original server CDF.
"""
import math


def radius(dispersion, gauss, uniform):
    value = abs(gauss(0.0, dispersion/2.0))
    if value > dispersion:
        value = dispersion*uniform(0.0, 1.0)
    # Folded normal plus the uniformly redistributed >2-sigma tail.
    old_centre = math.erf(.2/math.sqrt(2.0)) + .1*math.erfc(2.0/math.sqrt(2.0))
    if value < .1*dispersion and uniform(0.0, 1.0) >= .1/old_centre:
        value = dispersion*(.1+.1*uniform(0.0, 1.0))
    return value
