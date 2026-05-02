var key_metadata;
var key_stl;

function populate_types() {
    $.getJSON( keygen_endpoint, function( data ) {
        key_metadata = data;

        $("#key_type").empty();
        $.each(data, function(i, key_type) {
            $("#key_type").append($('<option/>', { 
                value: key_type.filename,
                text : key_type.name
            }));
        });
        if(key_metadata.length > 0) {
            $("#key_type").val(key_metadata[0].filename);
            populate_outlines_wardings();
            handle_hash();
        }
    });
}

function get_current_metadata() {
    var key_filename = $("#key_type").val();
    var found = null;
    $.each(key_metadata, function(i, key_type) {
        if(key_type.filename == key_filename) {
            found = key_type;
            return false;
        }
    });
    return found;
}

function update_warding_preview() {
    var warding = $("#key_warding").val();
    if (!warding) {
        $("#warding_preview_box").html('<div class="no_preview">No preview</div>');
        return;
    }

    $("#warding_preview_box").html('<div class="no_preview">Loading...</div>');

    var keyFile = $("#key_type").val() || "";
    fetch(keygen_endpoint + "/warding_preview?warding=" + encodeURIComponent(warding) + "&key=" + encodeURIComponent(keyFile))
        .then(function(resp) {
            if (!resp.ok) throw new Error("not found");
            return resp.text();
        })
        .then(function(svgText) {
            $("#warding_preview_box").html(svgText);
            var svgEl = $("#warding_preview_box svg")[0];
            var pathEl = $("#warding_preview_box #warding_path")[0];
            if (svgEl && pathEl) {
                try {
                    var bb = pathEl.getBBox();
                    var pad = Math.max(bb.width, bb.height) * 0.08;
                    svgEl.setAttribute("viewBox",
                        (bb.x - pad) + " " + (bb.y - pad) + " " +
                        (bb.width + pad*2) + " " + (bb.height + pad*2));
                    svgEl.setAttribute("preserveAspectRatio", "xMidYMid meet");
                } catch(e) {}
            }
        })
        .catch(function() {
            $("#warding_preview_box").html('<div class="no_preview">No preview available</div>');
        });
}

function populate_outlines_wardings() {
    var meta = get_current_metadata();
    if (!meta) return;

    $("#key_outline").empty();
    $("#key_warding").empty();

    $.each(meta.outlines, function(i, key_outline) {
        $("#key_outline").append($('<option/>', {
            value: key_outline,
            text : key_outline
        }));
    });
    $.each(meta.wardings, function(i, key_warding) {
        $("#key_warding").append($('<option/>', {
            value: key_warding,
            text : key_warding
        }));
    });
    $("#key_description").text(meta.description);

    // Show/hide extra param fields
    $(".extra_field").hide();
    if (meta.extra_params) {
        $.each(meta.extra_params, function(pname, pdefault) {
            var field = $("#field_" + pname);
            if (field.length) {
                field.show();
                $("#param_" + pname).val(pdefault);
            }
        });
    }

    // Always update preview immediately when type or warding changes
    update_warding_preview();
}

function generate_key() {
    $("#generated_key").hide();
    $("#generate_button").prop("disabled", true);
    $("#description").hide();
    $("#please_wait").show();

    var params = {
        "key":     $("#key_type").val(),
        "outline": $("#key_outline").val(),
        "warding": $("#key_warding").val(),
        "bitting": $("#key_bitting").val(),
    };

    var meta = get_current_metadata();
    if (meta && meta.extra_params) {
        $.each(meta.extra_params, function(pname) {
            var field = $("#field_" + pname);
            if (field.length && field.is(":visible")) {
                params[pname] = $("#param_" + pname).val();
            }
        });
    }

    var encoded = btoa(unescape(encodeURIComponent(JSON.stringify(params))));
    history.replaceState(null, null, "#" + encoded);

    var xhr = new XMLHttpRequest();
    xhr.open("GET", keygen_endpoint + "?" + $.param(params), true);
    xhr.responseType = "arraybuffer";

    xhr.onload = function(e) {
        if (this.status == 200) {
            key_stl = this.response;
            preview_load(key_stl);
            preview_animate();
            $("#generated_key").show();

            var blob = new Blob([key_stl], {type: "application/sla"});
            var objectUrl = URL.createObjectURL(blob);
            var bitting = $("#key_bitting").val();
            var filename = (bitting ? bitting : "keyblank") + ".stl";
            $("#key_download").attr("href", objectUrl).attr("download", filename);
        } else {
            alert("An error occurred");
        }
        $("#please_wait").hide();
        $("#generate_button").prop("disabled", false);
    };

    xhr.send();
}

function handle_hash() {
    hash = window.location.hash;
    if(hash == "#about") {
        $("#generator").hide();
        $("#about").show();
        $("#about_link").hide();
    } else {
        $("#about").hide();
        $("#generator").show();
        $("#about_link").show();

        try {
            var decoded = JSON.parse(decodeURIComponent(escape(atob(window.location.hash.substr(1)))));
            if (decoded && decoded.key) {
                $("#key_type").val(decoded.key);
                populate_outlines_wardings();
                $("#key_outline").val(decoded.outline);
                $("#key_warding").val(decoded.warding);
                $("#key_bitting").val(decoded.bitting);
                $.each(decoded, function(k, v) {
                    if ($("#param_" + k).length) {
                        $("#param_" + k).val(v);
                    }
                });
                generate_key();
            }
        } catch(e) {
            // ignore invalid/old hash format
        }
    }
}

$(document).ready(function() {
    $("#key_type").on("change", populate_outlines_wardings);
    $("#key_warding").on("change", update_warding_preview);
    $("#key_form").submit(function(e) {generate_key(); e.preventDefault();});
    $(window).on('hashchange', handle_hash);

    populate_types();
    preview_init();
});
