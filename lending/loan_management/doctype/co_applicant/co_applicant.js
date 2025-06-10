// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Co Applicant', {
    refresh: function(frm) {
        // Add any custom buttons or actions here
    },

    pan_number: function(frm) {
        // Convert PAN to uppercase
        if (frm.doc.pan_number) {
            frm.set_value('pan_number', frm.doc.pan_number.toUpperCase());
        }
    },

    contact_number: function(frm) {
        // Format contact number
        if (frm.doc.contact_number) {
            // Remove any non-digit characters
            let contact = frm.doc.contact_number.replace(/\D/g, '');
            frm.set_value('contact_number', contact);
        }
    },

    email: function(frm) {
        // Convert email to lowercase
        if (frm.doc.email) {
            frm.set_value('email', frm.doc.email.toLowerCase());
        }
    }
});

frappe.listview_settings["Co Applicant"] = {
    hide_name_column: true,
    add_fields: ["reference_type", "reference_name"],

    button: {
      show: function(doc) {
        return doc.reference_name;
      },
      get_label: function() {
        return __("Open", null, "Access");
      },
      get_description: function(doc) {
        return __("Open {0}", [
          `${__(doc.reference_type)}: ${doc.reference_name}`
        ]);
      },
      action: function(doc) {
        frappe.set_route("Form", doc.reference_type, doc
          .reference_name);
      },
    }
}
