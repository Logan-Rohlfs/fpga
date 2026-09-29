# Usage from repository root:
# vivado -mode batch -source scripts/build.tcl -tclargs blink
# vivado -mode batch -source scripts/build.tcl -tclargs sdr

if {$argc != 1} {
    error "Usage: vivado -mode batch -source scripts/build.tcl -tclargs blink|sdr"
}
set project [lindex $argv 0]
if {$project ni {blink sdr}} {
    error "Unknown project '$project'; expected blink or sdr"
}

set repo [file normalize [file join [file dirname [info script]] ..]]
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
create_project -in_memory -part $part
set_property target_language Verilog [current_project]

foreach src $sources {
    read_verilog -sv $src
}
read_xdc [file join $project_dir constraints basys3.xdc]

synth_design -top $top -part $part
opt_design
place_design
route_design

report_utilization -file [file join $out_dir utilization.rpt]
report_timing_summary -file [file join $out_dir timing.rpt]
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

