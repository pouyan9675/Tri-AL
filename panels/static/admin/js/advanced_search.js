const $ = django.jQuery;

document.getElementById("switch-checkbox").addEventListener('click', function () {
    var checkboxvar = document.getElementById('switch-checkbox');
    var labelvar = document.getElementById('switch-text');
    console.log(checkboxvar);
    console.log(labelvar);
    if (!checkboxvar.checked) {
        labelvar.innerHTML = "No";
    }
    else {
        labelvar.innerHTML = "Yes";
    }
});

$('input[name="start-date"]').daterangepicker({
    opens: 'right',
    drops: 'auto',
    autoUpdateInput: false,
}, function(start, end, label) {
    $('input[name="start-date"]').val(start.format('MM/DD/YYYY') + ' - ' + end.format('MM/DD/YYYY'));
});

$('input[name="first-posted"]').daterangepicker({
    opens: 'right',
    drops: 'auto',
    autoUpdateInput: false,
}, function(start, end, label) {
    $('input[name="first-posted"]').val(start.format('MM/DD/YYYY') + ' - ' + end.format('MM/DD/YYYY'));
});
$('input[name="last-update"]').daterangepicker({
    opens: 'left',
    drops: 'auto',
    autoUpdateInput: false,
}, function(start, end, label) {
    $('input[name="last-update"]').val(start.format('MM/DD/YYYY') + ' - ' + end.format('MM/DD/YYYY'));
});
$('input[name="end-date"]').daterangepicker({
    opens: 'left',
    drops: 'auto',
    autoUpdateInput: false,
}, function(start, end, label) {
    $('input[name="end-date"]').val(start.format('MM/DD/YYYY') + ' - ' + end.format('MM/DD/YYYY'));
});


function advancedSearch(){

    $('#search-results #loading').css("visibility", "visible");
    window.scrollTo({top: 0, behavior: 'smooth'});

    if ($('button[data-bs-target="#fieldsContainer"]').attr("aria-expanded") == 'true'){
        $('button[data-bs-target="#fieldsContainer"]').click();
    }


    var filters = $('#search-filters').serializeArray();


    if ($(this).attr('id') == 'form-submit'){
        var data = {
            'csrfmiddlewaretoken': window.CSRF_TOKEN,
            'page': 1,
        }
        for(i=0; i<filters.length; i++) {
            var pair = filters[i];
            if(pair["value"].length > 0){
                if(pair["name"] in data){
                    data[pair["name"]].push(pair["value"]);
                }else{
                    data[pair["name"]] = [pair["value"]];
                }
            }
        }
        window.SEARCH_DATA = data;
    } else {
        data = window.SEARCH_DATA;
        data['page'] = $(this).attr('value');
    }



    $.ajax({
        url: window.AJAX_URL,
        data: data,
        dataType: "html",
        success: function (response) {
            $('#search-results').html(response);

            /* Appearance Animations */
            var children = $("#search-results > .row").children();
            children.hide();
            for(i=0; i<children.length; i++){
                $(children[i]).fadeIn(200+(i/2)*120);
            }

            $('.search-submit').click(advancedSearch);

        },
      });

    
}


$('#form-submit').click(advancedSearch);


