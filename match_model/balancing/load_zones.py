# Copyright (c) 2015-2019 The Switch Authors. All rights reserved.
# Licensed under the Apache License, Version 2.0, which can be found at http://www.apache.org/licenses/LICENSE-2.0.

# Modifications copyright (c) 2022 The MATCH Authors. All rights reserved.
# Licensed under the GNU AFFERO GENERAL PUBLIC LICENSE Version 3 (or later), which is in the LICENSE file.


"""
Defines load zone parameters for the Match model.
"""
import os
from pyomo.environ import *
from match_model.reporting import write_table

dependencies = "match_model.timescales"
optional_dependencies = "match_model.transmission.local_td"


def define_dynamic_lists(mod):
    """
    Zone_Power_Injections and Zone_Power_Withdrawals are lists of
    components that contribute to load-zone level power balance equations.
    sum(Zone_Power_Injections[z,t]) == sum(Zone_Power_Withdrawals[z,t])
        for all z,t
    Other modules may append to either list, as long as the components they
    add are indexed by [zone, timepoint] and have units of MW. Other modules
    often include Expressions to summarize decision variables on a zonal basis.
    """
    mod.Zone_Power_Injections = []
    mod.Zone_Power_Withdrawals = []


def define_components(mod):
    """
    Augments a Pyomo abstract model object with sets and parameters that
    describe load zones and associated power balance equations. Unless
    otherwise stated, each set and parameter is mandatory.

    LOAD_ZONES is the set of load zones. Each zone is effectively modeled as a
    single bus connected to the inter-zonal transmission network (assuming
    transmission is enabled). If local_td is included, the central zonal bus,
    is connected to a "distributed bus" via local transmission and
    distribution that incurs efficiency losses and must be upgraded over time
    to always meet peak demand. Load zones are abbreviated as zone in
    parameter names and as z for indexes.

    zone_demand_mw[z,t] describes the power demand from the high voltage
    transmission grid each load zone z and timepoint t. This will either go
    into the Zone_Power_Withdrawals or the Distributed_Power_Withdrawals power
    balance equations, depending on whether the local_td module is included
    and has defined a distributed node for power balancing. If the local_td
    module is excluded, this value should be the total withdrawals from the
    central grid and should include any distribution losses. If the local_td
    module is included, this should be set to total end-use demand (aka sales)
    and should not include distribution losses. zone_demand_mw must be
    non-negative.

    Derived parameters:

    zone_total_demand_in_period_mwh[z,p] describes the total energy demand
    of each load zone in each period in Megawatt hours.

    """

    mod.LOAD_ZONES = Set(dimen=1)
    mod.ZONE_TIMEPOINTS = Set(
        dimen=2,
        initialize=lambda m: m.LOAD_ZONES * m.TIMEPOINTS,
        doc="The cross product of load zones and timepoints, used for indexing.",
    )
    mod.zone_demand_mw = Param(mod.ZONE_TIMEPOINTS, within=NonNegativeReals)
    mod.min_data_check("LOAD_ZONES", "zone_demand_mw")
    try:
        mod.Distributed_Power_Withdrawals.append("zone_demand_mw")
    except AttributeError:
        mod.Zone_Power_Withdrawals.append("zone_demand_mw")

    mod.zone_total_demand_in_period_mwh = Param(
        mod.LOAD_ZONES,
        mod.PERIODS,
        within=NonNegativeReals,
        initialize=lambda m, z, p: (
            sum(m.zone_demand_mw[z, t] * m.tp_weight[t] for t in m.TPS_IN_PERIOD[p])
        ),
    )


def define_dynamic_components(mod):
    """
    Adds components to a Pyomo abstract model object to enforce the
    first law of thermodynamics at the level of load zone buses. Unless
    otherwise stated, all terms describing power are in units of MW and
    all terms describing energy are in units of MWh.

    Zone_Energy_Balance[load_zone, timepoint] is a constraint that mandates
    conservation of energy in every load zone and timepoint. This constraint
    sums the model components in the lists Zone_Power_Injections and
    Zone_Power_Withdrawals - each of which is indexed by (z, t) and
    has units of MW - and ensures they are equal. The term tp_duration_hrs
    is factored out of the equation for brevity.
    """

    mod.Zone_Energy_Balance = Constraint(
        mod.ZONE_TIMEPOINTS,
        rule=lambda m, z, t: (
            sum(getattr(m, component)[z, t] for component in m.Zone_Power_Injections)
            == sum(
                getattr(m, component)[z, t] for component in m.Zone_Power_Withdrawals
            )
        ),
    )


def load_inputs(mod, match_data, inputs_dir):
    """
    Import load zone data. The following tab-separated files are
    expected in the input directory. Their index columns need to be on
    the left, but the data columns can be in any order. Extra columns
    will be ignored during import, and optional columns can be dropped.
    Other modules (such as local_td) may look for additional columns in
    some of these files. If you don't want to specify data for any
    optional parameter, use a dot . for its value. Optional columns and
    files are noted with a *.

    load_zones.csv
        LOAD_ZONE

    loads.csv
        LOAD_ZONE, TIMEPOINT, zone_demand_mw


    """
    # Include select in each load() function so that it will check out
    # column names, be indifferent to column order, and throw an error
    # message if some columns are not found.
    match_data.load_aug(
        filename=os.path.join(inputs_dir, "load_zones.csv"), set=mod.LOAD_ZONES
    )
    match_data.load_aug(
        filename=os.path.join(inputs_dir, "loads.csv"),
        autoselect=True,
        param=[mod.zone_demand_mw],
    )


def post_solve(instance, outdir):
    """
    Export results.

    load_balance.csv is a wide table of energy balance components for every
    zone and timepoint. Each component registered with
    Zone_Power_Injections and Zone_Power_Withdrawals will
    become a column.

    """
    write_table(
        instance,
        instance.LOAD_ZONES,
        instance.TIMEPOINTS,
        output_file=os.path.join(outdir, "load_balance.csv"),
        headings=(
            "load_zone",
            "timestamp",
        )
        + tuple(instance.Zone_Power_Injections + instance.Zone_Power_Withdrawals)
        + ("ZoneTotalExcessGen",),
        values=lambda m, z, t: (
            z,
            m.tp_timestamp[t],
        )
        + tuple(
            getattr(m, component)[z, t]
            for component in (m.Zone_Power_Injections + m.Zone_Power_Withdrawals)
        )
        + (m.ZoneTotalExcessGen[z, t],),
    )
