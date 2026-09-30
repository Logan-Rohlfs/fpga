# Usage from repository root:
# vivado -mode batch -source scripts/build.tcl -tclargs blink
# vivado -mode batch -source scripts/build.tcl -tclargs sdr
# vivado -mode batch -source scripts/build.tcl -tclargs sdr demo
#
# Inputs (keep in step with tools/sdr_cli/core.py:source_files): direct
# projects/<project>/rtl/*.v and *.sv, projects/<project>/rom/*.mem memory
# images, and constraints/basys3.xdc. The optional "demo" variant sets the
# sdr_top generic DEMO_FLIGHT=1 (APEX flight replay); the default is unchanged.
#
# Optional third argument: general.maxThreads (1..8), chosen by the host tool so
# concurrent builds share the machine. Omitted, Vivado keeps its own default.
# Use "default" as the variant to set threads without the demo:
# vivado -mode batch -source scripts/build.tcl -tclargs sdr default 6

if {$argc < 1 || $argc > 3} {
    error "Usage: vivado -mode batch -source scripts/build.tcl -tclargs blink|sdr \[default|demo \[threads\]\]"
}
set project [lindex $argv 0]
if {$project ni {blink sdr}} {
    error "Unknown project '$project'; expected blink or sdr"
}
set variant [expr {$argc >= 2 ? [lindex $argv 1] : "default"}]
set threads [expr {$argc == 3 ? [lindex $argv 2] : ""}]
if {$threads ne "" && (![string is integer -strict $threads] || $threads < 1 || $threads > 8)} {
    error "Thread count '$threads' must be an integer from 1 to 8 (general.maxThreads limit)"
}
if {$variant ni {default demo}} {
    error "Unknown variant '$variant'; expected demo"
}
if {$variant eq "demo" && $project ne "sdr"} {
    error "The demo variant exists only for the sdr project"
}

set repo [file normalize [file join [file dirname [info script]] ..]]
# $readmemh paths in the RTL are relative to the repository root.
cd $repo
set project_dir [file join $repo projects $project]
set rtl_dir [file join $project_dir rtl]
set out_dir [file join $repo build $project]
set top [expr {$project eq "blink" ? "blink" : "sdr_top"}]
set part xc7a35tcpg236-1

set sources [concat [glob -nocomplain -directory $rtl_dir *.v] [glob -nocomplain -directory $rtl_dir *.sv]]
if {[llength $sources] == 0} {
    error "No Verilog sources in $rtl_dir. Add $top.sv before building."
}

file mkdir $out_dir
if {$threads ne ""} {
    set_param general.maxThreads $threads
}
create_project -in_memory -part $part
set_property target_language Verilog [current_project]

foreach src $sources {
    read_verilog -sv $src
}
foreach mem [lsort [glob -nocomplain -directory [file join $project_dir rom] *.mem]] {
    read_mem $mem
}
read_xdc [file join $project_dir constraints basys3.xdc]

if {$variant eq "demo"} {
    synth_design -top $top -part $part -generic DEMO_FLIGHT=1
} else {
    synth_design -top $top -part $part
}
opt_design
place_design
route_design

report_utilization -file [file join $out_dir utilization.rpt]
# Per-module breakdown appended to the same fetched report.
report_utilization -hierarchical -append -file [file join $out_dir utilization.rpt]
report_timing_summary -max_paths 20 -file [file join $out_dir timing.rpt]
# One summary line per worst endpoint, so failures in every module are visible.
report_timing -max_paths 100 -nworst 1 -path_type summary -append -file [file join $out_dir timing.rpt]
report_drc -file [file join $out_dir drc.rpt]

set worst_path [get_timing_paths -max_paths 1]
if {[llength $worst_path] > 0} {
    set slack [get_property SLACK $worst_path]
    if {$slack < 0} {
        error "Timing failed: worst slack is $slack ns. See [file join $out_dir timing.rpt]"
    }
}

write_bitstream -force [file join $out_dir ${project}.bit]
puts "Built [file join $out_dir ${project}.bit]"

